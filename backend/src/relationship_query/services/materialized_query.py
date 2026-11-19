"""统一让列表、对比、证据和导出消费图中的已物化人物关系。"""

from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
from typing import cast

from relationship_query.contracts import (
    ConnectionSummary,
    Evidence,
    EvidenceResponse,
    ExpandRequest,
    ExpandResponse,
    ExportItem,
    ExportRequest,
    ExportResponse,
    FactView,
    GraphData,
    PersonItem,
    RelationScope,
    RelationSummary,
    SearchRequest,
    SearchResponse,
)
from relationship_query.domain.models import RelationType
from relationship_query.domain.path_budget import (
    PathBudget,
    PathBudgetExceeded,
    shared_relation_budget,
)
from relationship_query.services.connections import connection_details
from relationship_query.services.evidence import format_evidence, sort_evidence
from relationship_query.services.graph import build_graph
from relationship_query.services.graph_paths import GraphPathService
from relationship_query.services.ports import (
    BackgroundReader,
    MaterializedRelationRepository,
    QueryRepository,
    RelationPlanEngine,
)
from relationship_query.services.query import QueryError, QueryService
from relationship_query.services.query_plan import (
    PersonPagePlan,
    cached_plan,
    store_plan,
    supplied_plan,
)


class MaterializedQueryService(QueryService):
    def __init__(self, repository: QueryRepository, graph: MaterializedRelationRepository) -> None:
        super().__init__(repository)
        self.graph = graph
        self.plan_engine = (
            cast(RelationPlanEngine, graph) if hasattr(graph, "open_traversal") else None
        )
        self.background = (
            cast(BackgroundReader, repository) if hasattr(repository, "select_background") else None
        )

    def select_page(self, request: SearchRequest, reference_id: str | None) -> PersonPagePlan:
        try:
            return self._select_page(request, reference_id)
        except PathBudgetExceeded as error:
            raise QueryError(
                "GRAPH_QUERY_LIMIT", f"人物页计划达到预算（{error.label}），请缩小范围", 503
            ) from None

    def _select_page(self, request: SearchRequest, reference_id: str | None) -> PersonPagePlan:
        key = self.plan_key(request, reference_id)
        cache = getattr(self.graph, "cache", None)
        with shared_relation_budget() as budget:
            plan = self._ready_plan(key, budget)
            if plan is not None:
                return plan
            if reference_id is not None and self.plan_engine is not None:
                plan = self._relation_page(request, reference_id, budget)
            else:
                # 无中心SQL及历史兼容适配器仍使用其原有入口。
                plan = super().select_page(request, reference_id)
            if request.max_hops > 1 and plan.chains is None:
                assert reference_id is not None
                chains = self.graph.shortest_connections(
                    reference_id, list(plan.ids), request, budget
                )
                if set(chains) != set(plan.ids):
                    raise QueryError("GRAPH_INTEGRITY", "关联候选缺少对应连接链", 503)
                plan = replace(
                    plan, chains=tuple((key, tuple(path)) for key, path in chains.items())
                )
            store_plan(cache, plan, budget)
            return plan

    def _relation_page(
        self, request: SearchRequest, reference: str, budget: PathBudget
    ) -> PersonPagePlan:
        assert self.plan_engine is not None and self.background is not None
        self._validate_filters(request, reference)
        fingerprint = self._fingerprint(request, reference)
        after = self._decode_cursor(request.cursor, fingerprint) if request.cursor else None
        scope = RelationScope.model_validate(
            request.model_dump(include=set(RelationScope.model_fields))
        )
        found: list[str] = []
        with self.plan_engine.open_traversal(reference, scope, request.max_hops, budget) as view:
            while len(found) <= request.page_size:
                budget.check()
                block = view.block(after)
                if not block.ids:
                    if block.has_more:
                        raise QueryError("GRAPH_INTEGRITY", "空候选块不能声明后续页", 503)
                    break
                if (
                    list(block.ids) != sorted(set(block.ids))
                    or len(block.ids) > 128
                    or reference in block.ids
                    or (after is not None and block.ids[0] <= after)
                ):
                    raise QueryError("GRAPH_INTEGRITY", "候选块人物顺序异常", 503)
                selected = self.background.select_background(request, list(block.ids))
                found.extend(self.background.select_active_endpoints(selected))
                if not block.has_more:
                    break
                after = block.ids[-1]
            ids = found[: request.page_size]
            chains = view.chains(ids) if request.max_hops > 1 else None
            if chains is not None and set(chains) != set(ids):
                raise QueryError("GRAPH_INTEGRITY", "关联候选缺少对应连接链", 503)
            budget.check()
        has_more = len(found) > request.page_size
        return PersonPagePlan(
            self.repository.version,
            self.repository.reference_month,
            reference,
            fingerprint,
            tuple(ids),
            has_more,
            self._encode_cursor(ids[-1], fingerprint) if has_more else None,
            query_key=self.plan_key(request, reference),
            chains=tuple((key, tuple(path)) for key, path in chains.items())
            if chains is not None
            else None,
            probe_id=found[request.page_size] if has_more else None,
        )

    def plan_key(
        self, request: SearchRequest, reference_id: str | None, candidate_id: str | None = None
    ) -> str:
        prior = super().plan_key(request, reference_id, candidate_id)
        identity = getattr(self.repository, "release_key", "legacy")
        return sha256(f"{prior}|person-page-v3|{identity}".encode()).hexdigest()

    def select_evidence_plan(
        self, reference_id: str, candidate_id: str, request: SearchRequest
    ) -> PersonPagePlan:
        self._validate_filters(request, reference_id)
        key = self.plan_key(request, reference_id, candidate_id)
        cache = getattr(self.graph, "cache", None)
        with shared_relation_budget() as budget:
            prepared = self._ready_plan(key, budget)
        if prepared is not None:
            return prepared
        chains = {}
        if reference_id != candidate_id and self.repository.matches_background(
            request, candidate_id
        ):
            with shared_relation_budget() as budget:
                chains = self.graph.shortest_connections(
                    reference_id, [candidate_id], request, budget
                )
        plan = PersonPagePlan(
            self.repository.version,
            self.repository.reference_month,
            reference_id,
            self._fingerprint(request, reference_id),
            tuple(chains),
            False,
            None,
            query_key=key,
            chains=tuple((key, tuple(path)) for key, path in chains.items()),
        )
        with shared_relation_budget() as budget:
            store_plan(cache, plan, budget)
        return plan

    def _ready_plan(self, key: str, budget: PathBudget) -> PersonPagePlan | None:
        prepared = supplied_plan(key)
        if prepared is not None:
            return prepared
        plan = cached_plan(getattr(self.graph, "cache", None), key, budget)
        if plan is not None:
            # 直接Service／CLI调用也保留版本契约，不依赖HTTP包装器才安全。
            with self.graph.candidate_session(budget):
                pass
        return plan

    def search(self, request: SearchRequest, reference_id: str | None = None) -> SearchResponse:
        if request.max_hops == 1:
            return super().search(request, reference_id)
        return self._search_page(request, reference_id)[0]

    def _search_page(
        self, request: SearchRequest, reference_id: str | None
    ) -> tuple[SearchResponse, dict[str, list[str]]]:
        self._validate_filters(request, reference_id)
        assert reference_id is not None
        try:
            with shared_relation_budget() as budget:
                reference = self.require_person(reference_id)
                plan = self.select_page(request, reference_id)
                ids = list(plan.ids)
                chains = {key: list(path) for key, path in plan.chains or ()}
                with self.graph.graph_session(budget) as reader:
                    if set(chains) != set(ids):
                        raise QueryError("GRAPH_INTEGRITY", "关联候选缺少对应连接链", 503)
                    details = connection_details(
                        reader,
                        chains,
                        request,
                        evidence_limit=1,
                        verify_person_ids=(plan.probe_id,)
                        if plan.probe_id
                        and getattr(self.repository, "person_display", "snapshot") == "mysql-live"
                        else (),
                    )
                persons = {
                    person.id: person for detail in details.values() for person in detail.persons
                }
                views = {
                    view.fact.id: view
                    for detail in details.values()
                    for segment in detail.segments
                    for proof in segment.evidence
                    for view in (proof.reference, proof.candidate)
                }
                items = [
                    PersonItem(
                        person=persons[person],
                        relations=[
                            RelationSummary(
                                type=proof.relation_type,
                                label=proof.label,
                                entity_name=proof.entity.name,
                                evidence_id=proof.id,
                            )
                            for proof in details[person].segments[0].evidence
                        ]
                        if details[person].hop_count == 1
                        else [],
                        connection=ConnectionSummary(
                            hop_count=details[person].hop_count, person_ids=chains[person]
                        ),
                    )
                    for person in ids
                ]
                budget.check()
                response = SearchResponse(
                    **self.metadata(),
                    applied_filters=request,
                    reference=reference,
                    items=items,
                    has_more=plan.has_more,
                    next_cursor=plan.next_cursor,
                    graph=build_graph(
                        [reference, *persons.values()], list(views.values()), reference_id
                    ),
                )
                return response, chains
        except PathBudgetExceeded as error:
            raise QueryError(
                "GRAPH_QUERY_LIMIT", f"多跳查询达到预算（{error.label}），请降低跳数或缩小范围", 503
            ) from None

    def evidence(
        self, reference_id: str, candidate_id: str, filters: SearchRequest | None = None
    ) -> EvidenceResponse:
        if filters is None or filters.max_hops == 1:
            return super().evidence(reference_id, candidate_id, filters)
        self._validate_filters(filters, reference_id)
        reference, candidate = self.require_person(reference_id), self.require_person(candidate_id)
        try:
            with shared_relation_budget() as budget:
                details = {}
                plan = self.select_evidence_plan(reference_id, candidate_id, filters)
                chains = {key: list(path) for key, path in plan.chains or ()}
                if chains:
                    with self.graph.graph_session(budget) as reader:
                        details = connection_details(reader, chains, filters)
                detail = details.get(candidate_id)
                budget.check()
                return EvidenceResponse(
                    **self.metadata(),
                    reference=reference,
                    candidate=candidate,
                    items=detail.segments[0].evidence if detail and detail.hop_count == 1 else [],
                    connection=detail,
                )
        except PathBudgetExceeded:
            raise QueryError(
                "GRAPH_QUERY_LIMIT", "连接链取证达到预算，请降低跳数或缩小范围", 503
            ) from None

    def export_page(self, request: ExportRequest) -> ExportResponse:
        if request.filters.max_hops == 1:
            return super().export_page(request)
        if request.data_version != self.repository.version:
            raise QueryError("STALE_EXPORT", "数据版本已变化，请重新查询后导出", 409)
        try:
            with shared_relation_budget() as budget:
                result, chains = self._search_page(request.filters, request.reference_id)
                ids = [item.person.id for item in result.items]
                if ids != request.expected_person_ids:
                    raise QueryError("STALE_EXPORT", "当前页人物已变化，请重新查询后导出", 409)
                # 列表只取精简证据，其首条排序不能用完整导出证据的首条替代。
                # 复用已核验的链，不再执行第二轮多跳最短链计算。
                with self.graph.graph_session(budget) as reader:
                    details = connection_details(reader, chains, request.filters)
                views: dict[str, list[FactView]] = defaultdict(list)
                for view in self.repository.fact_views(ids):
                    views[view.fact.person_id].append(view)
                items = [
                    ExportItem(
                        **item.model_dump(),
                        facts=views[item.person.id],
                        evidence=details[item.person.id].segments[0].evidence
                        if details[item.person.id].hop_count == 1
                        else [],
                        connection_detail=details[item.person.id],
                    )
                    for item in result.items
                ]
                if (
                    sum(
                        len(item.facts)
                        + sum(len(s.evidence) for s in details[item.person.id].segments)
                        for item in items
                    )
                    > 5000
                ):
                    raise QueryError(
                        "EXPORT_LIMIT", "当前页经历与连接证据超过5000条，请缩小每页人数"
                    )
                budget.check()
                return ExportResponse(
                    **self.metadata(),
                    filters=request.filters,
                    reference=result.reference,
                    items=items,
                    has_more=result.has_more,
                )
        except PathBudgetExceeded as error:
            raise QueryError(
                "GRAPH_QUERY_LIMIT", f"多跳导出达到预算（{error.label}），请降低跳数或缩小范围", 503
            ) from None

    def expand(self, request: ExpandRequest) -> ExpandResponse:
        if request.filters.max_hops == 1:
            return super().expand(request)
        result = self.search(
            request.filters.model_copy(update={"page_size": 20, "cursor": None}), request.person_id
        )
        known_nodes, known_edges = set(request.existing_node_ids), set(request.existing_edge_ids)
        nodes = [node for node in result.graph.nodes if node.id not in known_nodes]
        trimmed_nodes = nodes[: 100 - len(known_nodes)]
        present = known_nodes | {node.id for node in trimmed_nodes}
        edges = [
            edge
            for edge in result.graph.edges
            if edge.id not in known_edges and edge.source in present and edge.target in present
        ]
        trimmed_edges = edges[: 200 - len(known_edges)]
        truncated = (
            result.has_more
            or result.graph.truncated
            or len(trimmed_nodes) < len(nodes)
            or len(trimmed_edges) < len(edges)
        )
        return ExpandResponse(
            **self.metadata(),
            has_more=result.has_more,
            graph=GraphData(
                nodes=trimmed_nodes,
                edges=trimmed_edges,
                truncated=truncated,
                truncation_reason="局部展开达到范围或画布上限，可设为中心分页查询"
                if truncated
                else None,
            ),
        )

    def _fingerprint(self, request: SearchRequest, reference_id: str | None) -> str:
        prior = super()._fingerprint(request, reference_id)
        identity = getattr(self.repository, "release_key", "legacy")
        return sha256(f"{prior}|materialized-cursor-v4|{identity}".encode()).hexdigest()

    def _proofs(
        self, pairs: list[tuple[str, str]], views: list[FactView], scope: RelationScope
    ) -> dict[tuple[str, str], list[Evidence]]:
        result: dict[tuple[str, str], list[Evidence]] = defaultdict(list)
        if not pairs:
            return result
        details = {v.fact.id: v for v in views}
        try:
            with self.graph.graph_session(PathBudget(5000, 5000)) as reader:
                proofs = reader.read_proofs(scope, pairs)
                for proof in proofs:
                    if proof.left_fact not in details or proof.right_fact not in details:
                        raise QueryError("GRAPH_INTEGRITY", "人物关系引用的 SQL 经历缺失", 503)
                    GraphPathService._check_detail(proof, details)
                    window = (
                        (proof.start_month, proof.end_month, proof.months)
                        if proof.start_month is not None
                        and proof.end_month is not None
                        and proof.months is not None
                        else None
                    )
                    result[(proof.left_person, proof.right_person)].append(
                        format_evidence(
                            details[proof.left_fact],
                            details[proof.right_fact],
                            proof.kind,
                            window,
                            require_same_school=scope.require_same_school,
                            scoped=bool(
                                scope.relation_start_month
                                or scope.relation_end_month
                                or scope.min_overlap_months
                            ),
                        )
                    )
        except PathBudgetExceeded as error:
            raise QueryError(
                "GRAPH_QUERY_LIMIT", f"图证据读取达到预算（{error.label}），请缩小查询范围", 503
            ) from None
        return {key: sort_evidence(items) for key, items in result.items()}

    def _build_evidence(
        self,
        left: list[FactView],
        right: list[FactView],
        reference_month: int,
        kind: RelationType | None = None,
        filters: RelationScope | None = None,
    ) -> list[Evidence]:
        if not left or not right:
            return []
        pair = left[0].fact.person_id, right[0].fact.person_id
        if pair[0] == pair[1]:
            return []
        scope = filters or RelationScope(relation_type=kind)
        return self._proofs([pair], left + right, scope).get(pair, [])
