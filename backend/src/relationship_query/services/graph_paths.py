"""图计算完整关系路径，SQL 仅按图返回标识读取来源详情。"""

from collections import defaultdict
from collections.abc import Callable
from hashlib import sha256
from time import monotonic

from relationship_query.contracts import (
    FactView,
    PathRequest,
    PathResponse,
    PathSegment,
    PersonPath,
)
from relationship_query.domain.graph_relations import GraphProof
from relationship_query.domain.models import Person
from relationship_query.domain.path_budget import PathBudgetExceeded
from relationship_query.services.evidence import format_evidence, sort_evidence
from relationship_query.services.paths import PathService, _SearchState
from relationship_query.services.ports import GraphRelationReader, GraphRelationRepository
from relationship_query.services.query import QueryError, QueryService


def integrity(message: str) -> QueryError:
    return QueryError("GRAPH_INTEGRITY", message, 503)


class GraphPathService(PathService):
    def __init__(
        self,
        repository: GraphRelationRepository,
        queries: QueryService,
        *,
        projection_id: str,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        super().__init__(
            repository, queries, query_backend="nebula", projection_id=projection_id, clock=clock
        )
        self.graph_repository = repository

    def search(self, request: PathRequest) -> PathResponse:
        state = self._new_state(request)
        try:
            with self.graph_repository.graph_session(state.budget) as reader:
                self._read_graph(reader, state)
                state.budget.check()
        except PathBudgetExceeded as exc:
            state.reasons.add(exc.reason)
        state.reasons.update(state.budget.candidate_reasons)
        return self._response(state)

    def _read_graph(self, reader: GraphRelationReader, state: _SearchState) -> None:
        left, right = state.reference, state.candidate
        cache: dict[str, FactView] = {}
        direct = reader.proofs(state.request, [(left.id, right.id)])
        self._load_details(reader, direct, cache)
        state.direct = self._graph_segment(state, left, right, direct, cache)
        state.direct_checked = True
        self._record_evidence_limit(state, state.direct)
        middle_ids = reader.paths(state.request)
        people = reader.persons(middle_ids) if middle_ids else {}
        if set(people) != set(middle_ids):
            raise integrity("图路径人物在 SQL 快照中缺失或已失效")
        for offset in range(0, len(middle_ids), 5):
            batch = middle_ids[offset : offset + 5]
            pairs = [(left.id, mid) for mid in batch] + [(mid, right.id) for mid in batch]
            proofs = reader.proofs(state.request, pairs)
            self._load_details(reader, proofs, cache)
            grouped: dict[tuple[str, str], list[GraphProof]] = defaultdict(list)
            for proof in proofs:
                grouped[(proof.left_person, proof.right_person)].append(proof)
            for mid in batch:
                first = self._graph_segment(
                    state, left, people[mid], grouped[(left.id, mid)], cache
                )
                second = self._graph_segment(
                    state, people[mid], right, grouped[(mid, right.id)], cache
                )
                if first is None or second is None:
                    raise integrity("图已返回连接链，但对应图证据缺失")
                self._record_evidence_limit(state, first, second)
                key = f"{left.id}|{mid}|{right.id}"
                state.paths.append(
                    PersonPath(
                        id="path:" + sha256(key.encode()).hexdigest()[:24],
                        intermediate=people[mid],
                        segments=(first, second),
                    )
                )

    @staticmethod
    def _load_details(
        reader: GraphRelationReader, proofs: list[GraphProof], cache: dict[str, FactView]
    ) -> None:
        ids = {key for p in proofs for key in (p.left_fact, p.right_fact)} - cache.keys()
        if ids:
            cache.update({v.fact.id: v for v in reader.fact_views_by_ids(sorted(ids))})
        if not ids.issubset(cache):
            raise integrity("图引用的原经历在 SQL 快照中缺失或失效")

    @staticmethod
    def _check_detail(proof: GraphProof, views: dict[str, FactView]) -> None:
        for fact_id, person_id, properties in (
            (proof.left_fact, proof.left_person, proof.left_properties),
            (proof.right_fact, proof.right_person, proof.right_properties),
        ):
            fact = views[fact_id].fact
            expected_type = {"same_school": "education", "same_major": "major"}.get(
                proof.kind, "employment"
            )
            if fact.type != expected_type:
                raise integrity("图关系类型与原经历类别不一致")
            excluded = {"id", "person_id", "entity_id", "type"}
            if "experience_key" not in properties:
                excluded.update(
                    {"experience_key", "position_title", "education_level", "is_regular_enrollment"}
                )
            expected = fact.model_dump(exclude=excluded)
            expected.update(fact_id=fact.id, kind=fact.type)
            if (
                fact.person_id != person_id
                or fact.entity_id != proof.entity_id
                or expected != properties
            ):
                raise integrity("图经历属性与 SQL 来源快照不一致")

    def _graph_segment(
        self,
        state: _SearchState,
        left: Person,
        right: Person,
        proofs: list[GraphProof],
        views: dict[str, FactView],
    ) -> PathSegment | None:
        if not proofs:
            return None
        scoped = any(
            v is not None
            for v in (
                state.request.scope.relation_start_month,
                state.request.scope.relation_end_month,
                state.request.scope.min_overlap_months,
            )
        )
        evidence = []
        for proof in proofs:
            state.budget.check_pair()
            self._check_detail(proof, views)
            window = (
                (proof.start_month, proof.end_month, proof.months)
                if proof.start_month is not None
                and proof.end_month is not None
                and proof.months is not None
                else None
            )
            evidence.append(
                format_evidence(
                    views[proof.left_fact],
                    views[proof.right_fact],
                    proof.kind,
                    window,
                    require_same_school=state.request.scope.require_same_school,
                    scoped=scoped,
                )
            )
        limit = state.request.limits.evidence_limit
        return PathSegment(
            id=f"segment:{left.id}|{right.id}",
            from_person=left,
            to_person=right,
            # 与原路径契约一致：先对包含探测项的前缀排序，再截取展示数。
            evidence=sort_evidence(evidence)[:limit],
            evidence_truncated=len(evidence) > limit,
        )
