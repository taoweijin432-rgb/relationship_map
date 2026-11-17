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
        with self.graph.candidate_session(budget):
            while len(found) <= request.page_size:
                block = self.graph.neighbor_block(reference_id, request, after, budget)
                if not block.ids:
                    break
                batch = list(block.ids)
                statement = (
                    select(self.tables.people.c.id)
                    .where(
                        self.tables.people.c.id.in_(batch),
                        self.tables.people.c.active.is_(True),
                        *self._filter_conditions(request),
                    )
                    .order_by(self.tables.people.c.id)
                )
                with self.engine.connect() as connection:
                    found.extend(connection.execute(statement).scalars())
                budget.check()
                if not block.has_more:
                    break
                after = batch[-1]
        return found[: request.page_size + 1]

    def matches_person(self, request: SearchRequest, reference_id: str, candidate_id: str) -> bool:
        if reference_id == candidate_id:
            return False
        if not self.matches_background(request, candidate_id):
            return False
        if request.max_hops == 1:
            return self.graph.connected(reference_id, candidate_id, request)
        return candidate_id in self.graph.shortest_connections(
            reference_id, [candidate_id], request, relation_query_budget()
        )
