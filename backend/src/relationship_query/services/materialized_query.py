"""统一让列表、对比、证据和导出消费图中的已物化人物关系。"""

from collections import defaultdict
from hashlib import sha256

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
from relationship_query.services.ports import MaterializedRelationRepository, QueryRepository
from relationship_query.services.query import QueryError, QueryService


class MaterializedQueryService(QueryService):
    def __init__(self, repository: QueryRepository, graph: MaterializedRelationRepository) -> None:
        super().__init__(repository)
        self.graph = graph

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
                with self.graph.graph_session(budget) as reader:
                    chains = reader.shortest_connections(reference_id, ids, request)
                    if set(chains) != set(ids):
                        raise QueryError("GRAPH_INTEGRITY", "关联候选缺少对应连接链", 503)
                    details = connection_details(reader, chains, request, evidence_limit=1)
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
                if reference_id != candidate_id and self.repository.matches_background(
                    filters, candidate_id
                ):
                    with self.graph.graph_session(budget) as reader:
                        chains = reader.shortest_connections(reference_id, [candidate_id], filters)
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
        return sha256((prior + "|materialized-cursor-v3-hops").encode()).hexdigest()

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
