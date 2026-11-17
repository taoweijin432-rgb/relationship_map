"""HTTP编排边界：ID计划可合并等待，每请求展示和证据在受限线程内装配。"""

from collections.abc import Callable
from functools import partial
from typing import TypeVar

from relationship_query.contracts import (
    ComparisonResponse,
    DatasetCounts,
    EvidenceResponse,
    ExpandRequest,
    ExpandResponse,
    ExportRequest,
    ExportResponse,
    PathRequest,
    PathResponse,
    PersonDetailsRequest,
    PersonDetailsResponse,
    SearchRequest,
    SearchResponse,
)
from relationship_query.domain.path_budget import relation_query_budget
from relationship_query.runtime.admission import Cost, QueryAdmission
from relationship_query.services.materialized_query import MaterializedQueryService
from relationship_query.services.paths import PathService
from relationship_query.services.query import QueryError, QueryService
from relationship_query.services.query_plan import PersonPagePlan, prepared_plan

T = TypeVar("T")


class QueryDispatch:
    def __init__(
        self,
        query: QueryService,
        paths: PathService,
        admission: QueryAdmission,
        counts: DatasetCounts,
    ) -> None:
        self.query, self.paths, self.admission = query, paths, admission
        self.counts = counts

    async def run(self, cost: Cost, operation: Callable[[], T]) -> T:
        return await self.admission.execute(cost, operation)

    async def search(self, body: SearchRequest, reference: str | None = None) -> SearchResponse:
        return await self._page(body, reference, partial(self.query.search, body, reference))

    async def expand(self, body: ExpandRequest) -> ExpandResponse:
        filters = body.filters.model_copy(update={"page_size": 20, "cursor": None})
        return await self._page(filters, body.person_id, partial(self.query.expand, body))

    async def export(self, body: ExportRequest) -> ExportResponse:
        if body.data_version != self.query.repository.version:
            raise QueryError("STALE_EXPORT", "数据版本已变化，请重新查询后导出", 409)
        # 完整导出保留整项重计算租约，不在计划与完整证据间重新排重队列。
        return await self.run(
            "heavy", partial(self._verified, partial(self.query.export_page, body))
        )

    async def evidence(
        self, reference: str, candidate: str, filters: SearchRequest | None = None
    ) -> EvidenceResponse:
        return await self.run(
            "heavy",
            partial(self._verified, partial(self.query.evidence, reference, candidate, filters)),
        )

    async def details(self, person_id: str, body: PersonDetailsRequest) -> PersonDetailsResponse:
        return await self.run(
            "heavy" if body.reference_id and body.reference_id != person_id else "light",
            partial(self._verified, partial(self.query.details, person_id, body)),
        )

    async def compare(self, reference: str, candidate: str) -> ComparisonResponse:
        return await self.run(
            "heavy", partial(self._verified, partial(self.query.compare, reference, candidate))
        )

    async def find_paths(self, body: PathRequest) -> PathResponse:
        return await self.run("heavy", partial(self._verified, partial(self.paths.search, body)))

    async def _page(
        self, body: SearchRequest, reference: str | None, operation: Callable[[], T]
    ) -> T:
        if not isinstance(self.query, MaterializedQueryService) or reference is None:
            return await self.run("heavy" if reference else "light", operation)
        query = self.query
        key = query.plan_key(body, reference)

        def select() -> PersonPagePlan:
            # 冷计划先检查身份；热计划的装配本身会实时检查，不再提前重复回源。
            query.require_person(reference)
            return query.select_page(body, reference)

        plan = await self.admission.page_plan(key, select, getattr(query.graph, "cache", None))

        def assemble() -> T:
            with prepared_plan(plan):
                return self._verified(operation)

        return await self.run("assembly", assemble)

    def _verified(self, operation: Callable[[], T]) -> T:
        if isinstance(self.query, MaterializedQueryService):
            # 缓存命中或空页也必须核对图发布；不能仅信任缓存中的版本字段。
            with self.query.graph.candidate_session(relation_query_budget()):
                return operation()
        return operation()
