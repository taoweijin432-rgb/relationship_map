"""v0.7 候选 SQL 的冻结参照，仅用于同数据性能与集合对照。"""

from sqlalchemy import exists, select
from sqlalchemy.engine import Connection

from relationship_query.contracts import PathRequest
from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.relation_sql import relation_pair_condition
from relationship_query.infrastructure.sqlite import facts, people, sources
from relationship_query.infrastructure.sqlite_paths import SQLitePathReader, SQLitePathRepository
from relationship_query.runtime.diagnostics import traced


class BaselinePathReader(SQLitePathReader):
    @traced("SQLitePathReader.candidates")
    def candidates(self, request: PathRequest) -> list[str]:
        self.budget.check()
        a, b = facts.alias("path_start_fact"), facts.alias("path_neighbor_fact")
        conditions = [
            a.c.person_id == request.reference_id,
            b.c.person_id.not_in([request.reference_id, request.candidate_id]),
            people.c.active.is_(True),
            relation_pair_condition(a, b, request.scope, self.reference_month),
        ]
        if request.intermediate_source:
            conditions.append(
                exists(
                    select(sources.c.person_id).where(
                        sources.c.person_id == people.c.id,
                        sources.c.source == request.intermediate_source,
                    )
                )
            )
        query = (
            select(b.c.person_id)
            .select_from(
                a.join(b, a.c.entity_id == b.c.entity_id).join(people, people.c.id == b.c.person_id)
            )
            .where(*conditions)
            .distinct()
            .order_by(b.c.person_id)
            .limit(request.limits.candidate_limit + 1)
        )
        result = list(self.connection.execute(query).scalars())
        self.budget.check()
        return result


class BaselinePathRepository(SQLitePathRepository):
    def _reader(self, connection: Connection, budget: PathBudget) -> SQLitePathReader:
        return BaselinePathReader(connection, budget, self.reference_month)
