"""两个 SQL 引擎复用的筛选、分页及事实读取；不包含建库和数据导入。"""

import re
from typing import Any

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import ColumnElement

from relationship_query.contracts import DatasetCounts, FactView, SearchRequest
from relationship_query.domain.models import Entity, Fact, Person
from relationship_query.infrastructure.read_model import QueryTables, dataset_meta
from relationship_query.infrastructure.relation_sql import (
    neighborhood_probe,
    relation_pair_condition,
)
from relationship_query.runtime.diagnostics import observe, traced
from relationship_query.runtime.fact_indexes import current_fact_indexes


def prefix_match(engine: Engine, column: Any, keyword: str) -> Any:
    if engine.dialect.name != "mysql":
        return column.startswith(keyword, autoescape=True)
    # 保持与SQLite相同的ASCII大小写规则，避免数据库排序规则扩大姓名匹配范围。
    pattern = "^" + "".join(
        f"[{letter.lower()}{letter.upper()}]"
        if letter.isascii() and letter.isalpha()
        else re.escape(letter)
        for letter in keyword
    )
    return func.regexp_like(column, pattern, "c")


class SQLRepository:
    def __init__(
        self,
        engine: Engine,
        *,
        tables: QueryTables | None = None,
        version: str | None = None,
        reference_month: int | None = None,
    ) -> None:
        self.engine = engine
        self.storage = "mysql-demo" if engine.dialect.name == "mysql" else "sqlite-demo"
        self.tables = tables or QueryTables()
        if version is not None and reference_month is not None:
            self.version, self.reference_month = version, reference_month
        else:
            with engine.connect() as connection:
                row = connection.execute(select(dataset_meta)).one()
                self.version, self.reference_month = row.version, row.reference_month

    @traced("SQLRepository.person")
    def person(self, person_id: str) -> Person | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(self.tables.people).where(
                        self.tables.people.c.id == person_id, self.tables.people.c.active.is_(True)
                    )
                )
                .mappings()
                .first()
            )
        return self.persons([person_id])[0] if row else None

    @traced("SQLRepository.persons")
    def persons(self, ids: list[str]) -> list[Person]:
        if not ids:
            return []
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.tables.people).where(self.tables.people.c.id.in_(ids))
                )
                .mappings()
                .all()
            )
            source_rows = connection.execute(
                select(self.tables.sources).where(self.tables.sources.c.person_id.in_(ids))
            ).all()
        mapping: dict[str, list[str]] = {person_id: [] for person_id in ids}
        for row in source_rows:
            mapping[row.person_id].append(row.source)
        return [
            Person.model_validate({**row, "sources": sorted(mapping[row["id"]])}) for row in rows
        ]

    @traced("SQLRepository.suggest_people")
    def suggest_people(self, keyword: str, limit: int) -> list[Person]:
        searchable = [self.tables.people.c.name]
        if "serial_number" in self.tables.people.c:
            searchable.append(self.tables.people.c.serial_number)
        with self.engine.connect() as connection:
            ids = (
                connection.execute(
                    select(self.tables.people.c.id)
                    .where(
                        self.tables.people.c.active.is_(True),
                        or_(*(self._prefix_match(column, keyword) for column in searchable)),
                    )
                    .order_by(self.tables.people.c.id)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
        return sorted(self.persons(list(ids)), key=lambda p: p.id)

    @traced("SQLRepository.suggest_entities")
    def suggest_entities(self, kind: str, keyword: str, limit: int) -> list[Entity]:
        alias_match = exists(
            select(self.tables.aliases.c.entity_id).where(
                self.tables.aliases.c.entity_id == self.tables.entities.c.id,
                self._prefix_match(self.tables.aliases.c.name, keyword),
            )
        )
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self.tables.entities)
                    .where(
                        self.tables.entities.c.type == kind,
                        or_(self._prefix_match(self.tables.entities.c.name, keyword), alias_match),
                    )
                    .order_by(self.tables.entities.c.id)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return [Entity.model_validate(row) for row in rows]

    def _prefix_match(self, column: Any, keyword: str) -> Any:
        return prefix_match(self.engine, column, keyword)

    @traced("SQLRepository.entity")
    def entity(self, entity_id: str) -> Entity | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(self.tables.entities).where(self.tables.entities.c.id == entity_id)
                )
                .mappings()
                .first()
            )
        return Entity.model_validate(row) if row else None

    @traced("SQLRepository.search_ids")
    def search_ids(
        self, request: SearchRequest, reference_id: str | None, after: str | None
    ) -> list[str]:
        conditions = self._search_conditions(request, reference_id)
        if after:
            conditions.append(self.tables.people.c.id > after)
        statement = (
            select(self.tables.people.c.id).where(*conditions).order_by(self.tables.people.c.id)
        )
        with self.engine.connect() as connection:
            return list(connection.execute(statement.limit(request.page_size + 1)).scalars())

    @traced("SQLRepository.matches_person")
    def matches_person(self, request: SearchRequest, reference_id: str, candidate_id: str) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.scalar(
                    select(self.tables.people.c.id).where(
                        *self._search_conditions(request, reference_id),
                        self.tables.people.c.id == candidate_id,
                    )
                )
                is not None
            )

    @traced("SQLRepository.matches_background")
    def matches_background(self, request: SearchRequest, person_id: str) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.scalar(
                    select(self.tables.people.c.id).where(
                        self.tables.people.c.id == person_id,
                        self.tables.people.c.active.is_(True),
                        *self._filter_conditions(request),
                    )
                )
                is not None
            )

    def _search_conditions(
        self, request: SearchRequest, reference_id: str | None
    ) -> list[ColumnElement[bool]]:
        conditions = [self.tables.people.c.active.is_(True), *self._filter_conditions(request)]
        if reference_id:
            conditions.extend(
                [
                    self.tables.people.c.id != reference_id,
                    self._relation_condition(reference_id, request),
                ]
            )
        return conditions

    @traced("SQLRepository.get_entities")
    def get_entities(self, ids: list[str]) -> list[Entity]:
        if not ids:
            return []
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(self.tables.entities).where(self.tables.entities.c.id.in_(ids))
            ).mappings()
            return [Entity.model_validate(row) for row in rows]

    def _filter_conditions(self, request: SearchRequest) -> list[ColumnElement[bool]]:
        result: list[ColumnElement[bool]] = []
        if request.source:
            result.append(
                exists(
                    select(self.tables.sources.c.person_id).where(
                        self.tables.sources.c.person_id == self.tables.people.c.id,
                        self.tables.sources.c.source == request.source,
                    )
                )
            )
        if request.school_ids:
            result.append(
                self._fact_exists(
                    self.tables.facts.c.type == "education",
                    self.tables.facts.c.entity_id.in_(request.school_ids),
                )
            )
        if request.major_ids:
            result.append(
                self._fact_exists(
                    self.tables.facts.c.type == "major",
                    self.tables.facts.c.entity_id.in_(request.major_ids),
                )
            )
        employment: list[ColumnElement[bool]] = []
        if request.position_titles:
            if "position_title" not in self.tables.facts.c:
                from relationship_query.services.query import QueryError

                raise QueryError("UNSUPPORTED_FILTER", "当前旧数据模式不支持原始职位筛选")
            employment.append(self.tables.facts.c.position_title.in_(request.position_titles))
        if request.organization_ids:
            employment.append(self.tables.facts.c.entity_id.in_(request.organization_ids))
        if request.role_ids:
            employment.append(self.tables.facts.c.role_id.in_(request.role_ids))
        if request.start_month:
            employment.append(self._effective_end(self.tables.facts) >= request.start_month)
        if request.end_month:
            employment.append(self.tables.facts.c.start_month <= request.end_month)
        if employment:
            result.append(self._fact_exists(self.tables.facts.c.type == "employment", *employment))
        return result

    def _fact_exists(self, *conditions: ColumnElement[bool]) -> ColumnElement[bool]:
        return exists(
            select(self.tables.facts.c.id).where(
                self.tables.facts.c.person_id == self.tables.people.c.id,
                self.tables.facts.c.active.is_(True),
                *conditions,
            )
        )

    def _effective_end(self, table: Any) -> Any:
        return case((table.c.is_current.is_(True), self.reference_month), else_=table.c.end_month)

    def _relation_condition(self, reference_id: str, request: SearchRequest) -> ColumnElement[bool]:
        a, b = self.tables.facts.alias("reference_fact"), self.tables.facts.alias("candidate_fact")
        query = (
            select(a.c.id)
            .select_from(a.join(b, a.c.entity_id == b.c.entity_id))
            .where(
                a.c.person_id == reference_id,
                b.c.person_id == self.tables.people.c.id,
                relation_pair_condition(a, b, request, self.reference_month),
            )
        )
        if self.engine.dialect.name == "mysql":
            with self.engine.connect() as connection:
                broad = (
                    len(
                        connection.execute(
                            neighborhood_probe(reference_id, request, self.tables.facts)
                        ).fetchmany(513)
                    )
                    > 512
                )
            if broad:
                # EXISTS 真值不变；对当前子查询禁用 semijoin，避免热门事实全量物化。
                query = query.prefix_with("/*+ NO_SEMIJOIN() */", dialect="mysql")
        return exists(query)

    @traced("SQLRepository.fact_views")
    def fact_views(self, ids: list[str]) -> list[FactView]:
        if not ids:
            return []
        indexes = current_fact_indexes()
        if indexes is None:
            return self._read_fact_views(ids)
        namespace = (id(self.engine), self.tables.facts.fullname, self.reference_month)
        missing = sorted({key for key in ids if (namespace, key) not in indexes.person_facts})
        observe("sql.person_facts_reused", len(set(ids)) - len(missing))
        if missing:
            views = self._read_fact_views(missing)
            for view in views:
                indexes.sql[(namespace, view.fact.id)] = view
            grouped: dict[str, list[str]] = {key: [] for key in missing}
            for view in views:
                grouped[view.fact.person_id].append(view.fact.id)
            indexes.person_facts.update(
                ((namespace, key), tuple(values)) for key, values in grouped.items()
            )
        fact_ids = {fact for key in ids for fact in indexes.person_facts[(namespace, key)]}
        return [indexes.sql[(namespace, fact)] for fact in sorted(fact_ids)]

    def _read_fact_views(self, ids: list[str]) -> list[FactView]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(self.tables.facts)
                .where(self.tables.facts.c.person_id.in_(ids), self.tables.facts.c.active.is_(True))
                .order_by(self.tables.facts.c.id)
            )
            fact_models = [Fact.model_validate(row) for row in rows.mappings()]
            entity_ids = {f.entity_id for f in fact_models} | {
                f.role_id for f in fact_models if f.role_id
            }
            entity_rows = connection.execute(
                select(self.tables.entities).where(self.tables.entities.c.id.in_(entity_ids))
            ).mappings()
            entity_map = {row["id"]: Entity.model_validate(row) for row in entity_rows}
        return [
            FactView(
                fact=f,
                entity=entity_map[f.entity_id],
                role=entity_map.get(f.role_id) if f.role_id else None,
            )
            for f in fact_models
        ]

    @traced("SQLRepository.counts")
    def counts(self) -> DatasetCounts:
        with self.engine.connect() as connection:

            def count(table: Any) -> int:
                return int(connection.scalar(select(func.count()).select_from(table)) or 0)

            result: DatasetCounts = {
                "person_count": connection.scalar(
                    select(func.count())
                    .select_from(self.tables.people)
                    .where(self.tables.people.c.active.is_(True))
                )
                or 0,
                "entity_count": count(self.tables.entities),
                "expert_count": 0,
                "resume_count": 0,
                "fact_count": connection.scalar(
                    select(func.count())
                    .select_from(self.tables.facts)
                    .join(
                        self.tables.people, self.tables.facts.c.person_id == self.tables.people.c.id
                    )
                    .where(
                        self.tables.facts.c.active.is_(True), self.tables.people.c.active.is_(True)
                    )
                )
                or 0,
            }

            def source_count(source: str) -> int:
                return int(
                    connection.scalar(
                        select(func.count())
                        .select_from(self.tables.sources)
                        .join(
                            self.tables.people,
                            self.tables.sources.c.person_id == self.tables.people.c.id,
                        )
                        .where(
                            self.tables.sources.c.source == source,
                            self.tables.people.c.active.is_(True),
                        )
                    )
                    or 0
                )

            result["expert_count"] = source_count("expert")
            result["resume_count"] = source_count("resume")
        return result
