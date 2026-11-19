"""静态成员计划：按完整最短前缀推进人物层，选页与恢复链共用工作区。"""

from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from relationship_query.contracts import RelationScope
from relationship_query.domain.graph_relations import NeighborBlock
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.member_index import MemberIndex
from relationship_query.runtime.diagnostics import observe, stage
from relationship_query.services.query import QueryError

UNSEEN = 2**32 - 1


def supports_member_plan(scope: RelationScope) -> bool:
    return (
        scope.relation_type is None
        and not scope.require_same_school
        and not scope.relation_organization_ids
        and scope.relation_start_month is None
        and scope.relation_end_month is None
        and scope.min_overlap_months is None
    )


@dataclass(frozen=True)
class MemberPlanLimits:
    workspace_bytes: int = 64 * 1024 * 1024
    member_scans: int = 5_000_000


class MemberTraversalView:
    def __init__(
        self,
        index: MemberIndex,
        reference: str,
        max_hops: int,
        budget: PathBudget,
        limits: MemberPlanLimits | None = None,
    ) -> None:
        if index.closed:
            raise RuntimeError("成员索引已关闭")
        if not 1 <= max_hops <= 4:
            raise ValueError("成员计划只支持1至4跳")
        self.index, self.budget = index, budget
        self.limits = limits or MemberPlanLimits()
        self.closed = False
        self.scans = 0
        self._checkpoint()
        n, m = len(index.people), len(index.entities)
        # 包含数组容量、两代前沿、Python排序键／整数／引用及当前页链的保守上界；
        # 在分配前拒绝，不能仅统计数组裸字节而漏掉排序临时对象。
        self.workspace_bytes = n * 256 + m + 32768
        observe("member.workspace_bytes", self.workspace_bytes)
        if self.workspace_bytes > self.limits.workspace_bytes:
            raise QueryError(
                "GRAPH_QUERY_LIMIT",
                "成员计划工作区达到容量边界",
                503,
                reason="budget.member_workspace",
            )
        self.predecessors = array("I", [UNSEEN]) * n
        self.distances = bytearray(n)
        self.ordered = array("I")
        source = bisect_left(index.people, reference)
        if source == n or index.people[source] != reference:
            self.close()
            raise QueryError("GRAPH_INTEGRITY", "中心人物在同版成员索引中缺失", 503)
        self.source = source
        try:
            with stage("Member.traversal"):
                self._traverse(max_hops)
        except BaseException:
            self.close()
            raise

    def _checkpoint(self) -> None:
        observe("member.checkpoints")
        try:
            self.budget.check()
        except PathBudgetExceeded as error:
            if error.reason == "cancelled":
                observe("member.cancel_observed")
            raise

    def _scan(self) -> None:
        if self.scans >= self.limits.member_scans:
            raise QueryError(
                "GRAPH_QUERY_LIMIT", "成员扫描达到作业边界", 503, reason="budget.member_scans"
            )
        self.scans += 1
        if self.scans % 1024 == 0:
            self._checkpoint()

    def _traverse(self, max_hops: int) -> None:
        index = self.index
        seen_entities = bytearray(len(index.entities))
        ranks = array("I", [0]) * len(index.people)
        self.predecessors[self.source] = self.source
        frontier = array("I", [self.source])
        try:
            for hop in range(1, max_hops + 1):
                self._checkpoint()
                following = self._expand_frontier(frontier, hop, seen_entities)
                if not following:
                    break
                self._checkpoint()
                if hop < max_hops:
                    with stage("Member.prefix_sort"):
                        following = array(
                            "I", sorted(following, key=lambda p: (ranks[self.predecessors[p]], p))
                        )
                    for rank, person in enumerate(following):
                        if rank % 1024 == 0:
                            self._checkpoint()
                        ranks[person] = rank
                self._checkpoint()
                frontier = following
            # 字典本来按完整人物ID排序，扫描距离数组即可，不能按跳数重新排序。
            with stage("Member.result_order"):
                self._checkpoint()
                for person, distance in enumerate(self.distances):
                    if person % 1024 == 0:
                        self._checkpoint()
                    if distance:
                        self.ordered.append(person)
                self._checkpoint()
        finally:
            observe("member.scans", self.scans)

    def _expand_frontier(self, frontier: array, hop: int, seen_entities: bytearray) -> array:
        index = self.index
        following = array("I")
        for person in frontier:
            for at in range(index.person_offsets[person], index.person_offsets[person + 1]):
                self._scan()
                entity = index.person_entities[at]
                if seen_entities[entity]:
                    continue
                # 首次到达实体的人物拥有最短且字典序最小的完整前缀。
                seen_entities[entity] = 1
                self._discover_members(entity, person, hop, following)
        return following

    def _discover_members(self, entity: int, person: int, hop: int, following: array) -> None:
        index = self.index
        for at in range(index.entity_offsets[entity], index.entity_offsets[entity + 1]):
            self._scan()
            candidate = index.entity_people[at]
            if self.predecessors[candidate] != UNSEEN:
                continue
            self.predecessors[candidate] = person
            self.distances[candidate] = hop
            following.append(candidate)

    def block(self, after: str | None, size: int = 128) -> NeighborBlock:
        self._check_open()
        if not 1 <= size <= 128:
            raise ValueError("候选块大小必须在1至128之间")
        boundary = bisect_right(self.index.people, after) if after is not None else 0
        start = bisect_left(self.ordered, boundary)
        ids = tuple(self.index.people[p] for p in self.ordered[start : start + size])
        return NeighborBlock(ids=ids, has_more=start + size < len(self.ordered))

    def chains(self, ids: list[str]) -> dict[str, list[str]]:
        self._check_open()
        if len(ids) > 128:
            raise ValueError("单次链恢复最多128个终点")
        result = {}
        with stage("Query.stable_chains"):
            for identity in ids:
                self._checkpoint()
                position = bisect_left(self.index.people, identity)
                if (
                    position >= len(self.index.people)
                    or self.index.people[position] != identity
                    or not self.distances[position]
                ):
                    continue
                chain = [position]
                while chain[-1] != self.source:
                    chain.append(self.predecessors[chain[-1]])
                result[identity] = [self.index.people[p] for p in reversed(chain)]
        self._checkpoint()
        # 原生链按跳数、终点ID返回；保持装配画布的数组顺序，候选页仍按ID排序。
        return {key: result[key] for key in sorted(result, key=lambda key: (len(result[key]), key))}

    def _check_open(self) -> None:
        if self.closed or self.index.closed:
            raise RuntimeError("遍历工作区或成员索引已关闭")
        self._checkpoint()

    def close(self) -> None:
        self.predecessors = array("I")
        self.distances = bytearray()
        self.ordered = array("I")
        self.closed = True
