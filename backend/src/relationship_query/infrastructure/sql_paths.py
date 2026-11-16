"""SQL 路径事实读取及等价候选语句；连接与执行中止由具体引擎管理。"""

from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.engine import Connection
from sqlalchemy.sql import Select

from relationship_query.contracts import FactView, PathRequest
from relationship_query.domain.models import Entity, Fact, Person
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.read_model import QueryTables
from relationship_query.infrastructure.relation_sql import (
    neighborhood_probe,
    relation_pair_condition,
)
from relationship_query.runtime.diagnostics import observe, traced
from relationship_query.runtime.fact_indexes import FactIndexes, current_fact_indexes


class SQLPathReader:
    def __init__(
        self,
        connection: Connection,
        budget: PathBudget,
        reference_month: int,
        tables: QueryTables | None = None,
    ) -> None:
        self.connection, self.budget, self.reference_month = connection, budget, reference_month
        self.tables = tables or QueryTables()
        self._indexes = current_fact_indexes() or FactIndexes()
        self._namespace = (id(connection.engine), self.tables.facts.fullname, reference_month)

    @traced("SQLPathReader.persons")
    def persons(self, ids: list[str]) -> dict[str, Person]:
        self.budget.check()
        records = (
            self.connection.execute(
                select(self.tables.people).where(
                    self.tables.people.c.id.in_(ids), self.tables.people.c.active.is_(True)
                )
            )
            .mappings()
            .all()
        )
        source_rows = self.connection.execute(
            select(self.tables.sources).where(self.tables.sources.c.person_id.in_(ids))
        )
        source_map: dict[str, list[str]] = {person_id: [] for person_id in ids}
        for row in source_rows:
            source_map[row.person_id].append(row.source)
        self.budget.check()
        return {
            row["id"]: Person.model_validate({**row, "sources": sorted(source_map[row["id"]])})
            for row in records
        }

    @traced("SQLPathReader.candidates")
    def candidates(self, request: PathRequest) -> list[str]:
        if self._broad_anchor(request):
            return self._ordered_candidates(request)
        return self._joined_candidates(request)

    @traced("SQLPathReader.degree_probe")
    def _broad_anchor(self, request: PathRequest) -> bool:
        self.budget.check()
        probe = neighborhood_probe(request.reference_id, request.scope, self.tables.facts)
        rows = self.connection.execute(probe).fetchmany(513)
        self.budget.check()
        return len(rows) > 512

    @traced("SQLPathReader.ordered_candidates")
    def _ordered_candidates(
        self, request: PathRequest, *, stop_at_first: bool = False
    ) -> list[str]:
        self.budget.check()
        query = self._candidate_query(request, stop_at_first=stop_at_first)
        result = list(
            self.connection.execute(query.limit(request.limits.candidate_limit + 1)).scalars()
        )
        self.budget.check()
        return result

    def qualify_candidates(self, request: PathRequest, ids: list[str]) -> list[str]:
        self.budget.check()
        if not ids:
            return []
        query = self._candidate_query(request, stop_at_first=True).where(
            self.tables.people.c.id.in_(ids)
        )
        result = list(self.connection.execute(query).scalars())
        self.budget.check()
        return result

    def _candidate_query(self, request: PathRequest, *, stop_at_first: bool) -> Select[Any]:
        a, b = (
            self.tables.facts.alias("path_start_fact"),
            self.tables.facts.alias("path_neighbor_fact"),
        )
        pairs = (
            select(a.c.id)
            .select_from(a.join(b, a.c.entity_id == b.c.entity_id))
            .where(
                a.c.person_id == request.reference_id,
                b.c.person_id == self.tables.people.c.id,
                relation_pair_condition(a, b, request.scope, self.reference_month),
            )
        )
        connected = exists(
            pairs.prefix_with("/*+ NO_SEMIJOIN() */", dialect="mysql") if stop_at_first else pairs
        )
        conditions = [
            self.tables.people.c.active.is_(True),
            self.tables.people.c.id.not_in([request.reference_id, request.candidate_id]),
            connected,
        ]
        if request.intermediate_source:
            conditions.append(
                exists(
                    select(self.tables.sources.c.person_id).where(
                        self.tables.sources.c.person_id == self.tables.people.c.id,
                        self.tables.sources.c.source == request.intermediate_source,
                    )
                )
            )
        return select(self.tables.people.c.id).where(*conditions).order_by(self.tables.people.c.id)

    @traced("SQLPathReader.joined_candidates")
    def _joined_candidates(self, request: PathRequest) -> list[str]:
        self.budget.check()
        a, b = (
            self.tables.facts.alias("path_start_fact"),
            self.tables.facts.alias("path_neighbor_fact"),
        )
        conditions = [
            a.c.person_id == request.reference_id,
            b.c.person_id.not_in([request.reference_id, request.candidate_id]),
            self.tables.people.c.active.is_(True),
            relation_pair_condition(a, b, request.scope, self.reference_month),
        ]
        if request.intermediate_source:
            conditions.append(
                exists(
                    select(self.tables.sources.c.person_id).where(
                        self.tables.sources.c.person_id == self.tables.people.c.id,
                        self.tables.sources.c.source == request.intermediate_source,
                    )
                )
            )
        query = (
            select(b.c.person_id)
            .select_from(
                a.join(b, a.c.entity_id == b.c.entity_id).join(
                    self.tables.people, self.tables.people.c.id == b.c.person_id
                )
            )
            .where(*conditions)
            .distinct()
            .order_by(b.c.person_id)
            .limit(request.limits.candidate_limit + 1)
        )
        result = list(self.connection.execute(query).scalars())
        self.budget.check()
        return result

    @traced("SQLPathReader.fact_views")
    def fact_views(self, ids: list[str]) -> list[FactView]:
        return self._fact_views(self.tables.facts.c.person_id.in_(ids))

    @traced("SQLPathReader.fact_views_by_ids")
    def fact_views_by_ids(self, ids: list[str]) -> list[FactView]:
        self.budget.check()
        ordered = sorted(set(ids))
        missing = [key for key in ordered if (self._namespace, key) not in self._indexes.sql]
        observe("sql.fact_reused", len(ordered) - len(missing))
        if missing:
            self._fact_views(self.tables.facts.c.id.in_(missing))
        return [
            self._indexes.sql[(self._namespace, key)]
            for key in ordered
            if (self._namespace, key) in self._indexes.sql
        ]

    def _fact_views(self, condition: Any) -> list[FactView]:
        self.budget.check()
        remaining = self.budget.fact_limit - self.budget.facts
        if remaining <= 0:
            raise PathBudgetExceeded("fact_limit")
        rows = (
            self.connection.execute(
                select(self.tables.facts)
                .where(condition, self.tables.facts.c.active.is_(True))
                .order_by(self.tables.facts.c.id)
                .limit(remaining + 1)
            )
            .mappings()
            .all()
        )
        self.budget.facts += min(len(rows), remaining)
        if len(rows) > remaining:
            raise PathBudgetExceeded("fact_limit")
        fact_models = [Fact.model_validate(row) for row in rows]
        entity_ids = {f.entity_id for f in fact_models} | {
            f.role_id for f in fact_models if f.role_id
        }
        entity_map = {
            row["id"]: Entity.model_validate(row)
            for row in self.connection.execute(
                select(self.tables.entities).where(self.tables.entities.c.id.in_(entity_ids))
            ).mappings()
        }
        self.budget.check()
        views = [
            FactView(fact=f, entity=entity_map[f.entity_id], role=entity_map.get(f.role_id or ""))
            for f in fact_models
        ]
        for view in views:
            self._indexes.sql[(self._namespace, view.fact.id)] = view
        return views
