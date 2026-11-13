"""图分块顺序召回候选，SQL 资格与 Domain 证据仍为最终判断依据。"""

import heapq
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import groupby
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from relationship_query.contracts import FactView, PathRequest
from relationship_query.domain.models import Person
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.graph_client import GraphClient
from relationship_query.infrastructure.graph_model import (
    BLOCK_SIZE,
    ids_digest,
    literal,
    read_manifest,
    read_reader,
    vid,
)
from relationship_query.infrastructure.graph_relations import NativeGraphReader
from relationship_query.infrastructure.snapshots import snapshot_digest
from relationship_query.runtime.diagnostics import traced
from relationship_query.services.ports import GraphRelationReader, PathReader, PathRepository
from relationship_query.services.query import QueryError


def integrity(message: str) -> QueryError:
    return QueryError("GRAPH_INTEGRITY", message, 503)


class GraphPathRepository:
    def __init__(self, sql: PathRepository, engine: Engine, manifest_path: Path) -> None:
        self.sql = sql
        self.version, self.reference_month = sql.version, sql.reference_month
        self.manifest = read_manifest(manifest_path)
        if (self.version, self.reference_month) != (
            self.manifest.data_version,
            self.manifest.reference_month,
        ):
            raise QueryError("GRAPH_VERSION_MISMATCH", "SQL 与图投影版本不一致", 409)
        with engine.connect() as connection:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN")
            if snapshot_digest(connection) != self.manifest.source_digest:
                raise QueryError("GRAPH_VERSION_MISMATCH", "SQL 内容与图投影快照不一致", 409)
        self.client = GraphClient(self.manifest, read_reader(manifest_path))
        self.client.check_version(PathBudget(3000, 5000))

    @contextmanager
    def session(self, budget: PathBudget) -> Iterator[PathReader]:
        with self.sql.session(budget) as reader:
            self.client.check_version(budget)
            yield GraphPathReader(reader, self.client, budget)
            self.client.check_version(budget)

    @contextmanager
    def graph_session(self, budget: PathBudget) -> Iterator[GraphRelationReader]:
        with self.sql.session(budget) as reader:
            self.client.check_version(budget)
            yield NativeGraphReader(reader, self.client, budget, self.reference_month)
            self.client.check_version(budget)


class GraphPathReader:
    def __init__(self, sql: PathReader, client: GraphClient, budget: PathBudget) -> None:
        self.sql, self.client, self.budget = sql, client, budget

    def persons(self, ids: list[str]) -> dict[str, Person]:
        return self.sql.persons(ids)

    def fact_views(self, ids: list[str]) -> list[FactView]:
        return self.sql.fact_views(ids)

    def fact_views_by_ids(self, ids: list[str]) -> list[FactView]:
        return self.sql.fact_views_by_ids(ids)

    def qualify_candidates(self, request: PathRequest, ids: list[str]) -> list[str]:
        return self.sql.qualify_candidates(request, ids)

    @traced("GraphPathReader.candidates")
    def candidates(self, request: PathRequest) -> list[str]:
        found: list[str] = []
        pending: list[str] = []
        try:
            entities = self._related_entities(request)
            streams = [
                self._entity_members(identity, properties) for identity, properties in entities
            ]
            for identity, _ in groupby(heapq.merge(*streams)):
                self.budget.check()
                pending.append(identity)
                if len(pending) == 64:
                    found.extend(self.qualify_candidates(request, pending))
                    pending = []
                    if len(found) > request.limits.candidate_limit:
                        return found[: request.limits.candidate_limit + 1]
        except PathBudgetExceeded as exc:
            if exc.reason != "graph_limit":
                raise
            self.budget.candidate_reasons.add("graph_limit")
        if pending:
            found.extend(self.qualify_candidates(request, pending))
        return found[: request.limits.candidate_limit + 1]

    def _related_entities(self, request: PathRequest) -> list[tuple[str, dict[str, Any]]]:
        person_vid = vid("p", request.reference_id)
        person = self.client.fetch("person", [person_vid], self.budget)[person_vid]
        if person["entities"] > 64:
            raise PathBudgetExceeded("graph_limit")
        rows = self.client.execute(
            f"GO FROM {literal(person_vid)} OVER affiliated "
            "YIELD properties(edge).entity_id AS entity_id, "
            "properties(edge).kind AS kind LIMIT [65]",
            self.budget,
            65,
        )
        identities = sorted(row["entity_id"] for row in rows)
        if len(rows) != person["entities"] or ids_digest(identities) != person["checksum"]:
            raise integrity("人物的图邻接记录不完整")
        scope = request.scope
        selected = [
            row["entity_id"]
            for row in rows
            if (
                (
                    scope.relation_type is None
                    or row["kind"]
                    == ("education" if scope.relation_type == "same_school" else "employment")
                )
                and (
                    not scope.relation_organization_ids
                    or row["entity_id"] in scope.relation_organization_ids
                )
            )
        ]
        if not selected:
            return []
        properties = self.client.fetch(
            "entity", [vid("e", identity) for identity in selected], self.budget
        )
        return [(identity, properties[vid("e", identity)]) for identity in sorted(selected)]

    def _entity_members(self, entity: str, properties: dict[str, Any]) -> Iterator[str]:
        members, blocks = properties["members"], properties["blocks"]
        if members <= 0 or blocks != (members + BLOCK_SIZE - 1) // BLOCK_SIZE:
            raise integrity("实体成员块元数据无效")
        previous: str | None = None
        for part in range(blocks):
            block = vid("b", entity, part)
            meta = self.client.fetch("roster", [block], self.budget)[block]
            rows = self.client.execute(
                f"GO FROM {literal(block)} OVER member "
                "YIELD properties(edge).person_id AS person_id LIMIT [129]",
                self.budget,
                129,
            )
            ids = sorted(row["person_id"] for row in rows)
            expected = min(BLOCK_SIZE, members - part * BLOCK_SIZE)
            if (
                meta["entity_id"] != entity
                or meta["part"] != part
                or meta["member_count"] != expected
                or len(ids) != expected
                or len(set(ids)) != len(ids)
                or ids_digest(ids) != meta["checksum"]
                or previous is not None
                and ids[0] <= previous
            ):
                raise integrity("图成员分块缺失、顺序或内容不一致")
            previous = ids[-1]
            yield from ids
