"""图召回候选、SQL筛选背景的共享只读仓储。"""

from typing import Any

from sqlalchemy import select

from relationship_query.contracts import SearchRequest
from relationship_query.domain.path_budget import relation_query_budget
from relationship_query.infrastructure.sql_repository import SQLRepository


class MaterializedSQLRepository(SQLRepository):
    graph: Any

    def search_ids(
        self, request: SearchRequest, reference_id: str | None, after: str | None
    ) -> list[str]:
        if reference_id is None:
            return super().search_ids(request, None, after)
        budget = relation_query_budget()
        found: list[str] = []
        with self.graph.candidate_session(budget), self.engine.connect() as connection:
            while len(found) <= request.page_size:
                page = self.graph.neighbor_page(reference_id, request, after, budget)
                if not page:
                    break
                batch = page[:128]
                statement = (
                    select(self.tables.people.c.id)
                    .where(
                        self.tables.people.c.id.in_(batch),
                        self.tables.people.c.active.is_(True),
                        *self._filter_conditions(request),
                    )
                    .order_by(self.tables.people.c.id)
                )
                found.extend(connection.execute(statement).scalars())
                budget.check()
                if len(page) <= 128:
                    break
                after = batch[-1]
        return found[: request.page_size + 1]

    def matches_person(self, request: SearchRequest, reference_id: str, candidate_id: str) -> bool:
        if reference_id == candidate_id:
            return False
        with self.engine.connect() as connection:
            matched = (
                connection.scalar(
                    select(self.tables.people.c.id).where(
                        self.tables.people.c.id == candidate_id,
                        self.tables.people.c.active.is_(True),
                        *self._filter_conditions(request),
                    )
                )
                is not None
            )
        if not matched:
            return False
        if request.max_hops == 1:
            return self.graph.connected(reference_id, candidate_id, request)
        with self.graph.graph_session(relation_query_budget()) as reader:
            return candidate_id in reader.shortest_connections(
                reference_id, [candidate_id], request
            )
