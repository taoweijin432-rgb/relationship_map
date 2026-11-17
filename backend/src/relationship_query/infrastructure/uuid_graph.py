"""读取已物化人物关系及逐段事实证据；不从 SQL 重算关系或路径。"""

from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import cast

from relationship_query.contracts import FactView, PathRequest, RelationScope, SearchRequest
from relationship_query.domain.graph_relations import PROOF_PAIR_BATCH, GraphProof, NeighborBlock
from relationship_query.domain.models import Person, RelationType
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.graph_client import GraphClient
from relationship_query.infrastructure.graph_model import literal, read_reader
from relationship_query.infrastructure.mysql import MySQLPathRepository
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.infrastructure.uuid_api import UUIDRepository
from relationship_query.infrastructure.uuid_projection import meta_properties
from relationship_query.runtime.diagnostics import observe
from relationship_query.runtime.fact_indexes import FactIndexes, current_fact_indexes
from relationship_query.runtime.relation_cache import RelationCache
from relationship_query.services.ports import PathReader, PathRepository
from relationship_query.services.query import QueryError

KINDS = {
    "same_company": "same_company",
    "company_overlap": "same_company_overlap",
    "same_school": "same_school",
    "same_major": "same_major",
}
FACTS = {
    "same_company": "worked_at",
    "company_overlap": "worked_at",
    "same_school": "studied_at",
    "same_major": "studied_major",
}


def relation_scope_key(scope: RelationScope) -> dict:
    return {
        **scope.model_dump(include=set(RelationScope.model_fields)),
        "max_hops": getattr(scope, "max_hops", 1),
    }


def kinds(scope: RelationScope) -> list[str]:
    if scope.relation_type == "same_company":
        return ["same_company", "company_overlap"]
    return [k for k, v in KINDS.items() if scope.relation_type in (None, v)]


def edge_filter(variable: str, scope: RelationScope) -> str:
    terms = []
    if scope.relation_organization_ids:
        entity_vids = ["e:" + i for i in scope.relation_organization_ids]
        terms.append(f"{variable}.entity_vid IN {literal(entity_vids)}")
    if scope.relation_type == "same_company_overlap":
        lo = f"{variable}.overlap_start_month"
        hi = f"{variable}.overlap_end_month"
        if scope.relation_start_month:
            lo = (
                f"CASE WHEN {lo}>={scope.relation_start_month} "
                f"THEN {lo} ELSE {scope.relation_start_month} END"
            )
        if scope.relation_end_month:
            hi = (
                f"CASE WHEN {hi}<={scope.relation_end_month} "
                f"THEN {hi} ELSE {scope.relation_end_month} END"
            )
        terms.append(f"({lo})<=({hi})")
        terms.append(
            f"(toInteger(({hi})/100)-toInteger(({lo})/100))*12"
            f"+({hi})%100-({lo})%100+1>={scope.min_overlap_months or 1}"
        )
    return " AND ".join(terms) or "true"


def school_requirement(scope: RelationScope, left: str, right: str) -> str:
    if not scope.require_same_school:
        return ""
    return f", ({left})-[:same_school]-({right})"


def connection_match(
    reference: str, scope: RelationScope, hops: int, *, paths: bool = True
) -> tuple[str, list[str]]:
    """召回每层折叠终点，最短链每层为一个终点保留字典序最小前缀。"""
    if not 1 <= hops <= 4:
        raise ValueError("Connection depth must be 1–4")
    vertices = [f"v{i}" for i in range(hops + 1)]
    pattern = "|".join(kinds(scope))
    clauses = []
    for index in range(hops):
        if index:
            if paths:
                sequence = "[id(v0),id(v1)]" if index == 1 else f"connection_ids+[id(v{index})]"
                # 最短链的每个前缀也是最短链，同终点的较大前缀可提前折叠。
                clauses.append(f"WITH v{index},min({sequence}) AS connection_ids")
            else:
                clauses.append(f"WITH DISTINCT v{index}")
        terms = [edge_filter(f"r{index}", scope)]
        if index == 0:
            terms.append(f"id(v0)=={literal(reference)}")
            terms.append("id(v0)!=id(v1)")
        elif paths:
            terms.append(f"NOT (id(v{index + 1}) IN connection_ids)")
        else:
            terms.append(f"id(v{index + 1})!={literal(reference)}")
        clauses.append(
            f"MATCH (v{index}:person)-[r{index}:{pattern}]-(v{index + 1}:person)"
            + school_requirement(scope, f"v{index}", f"v{index + 1}")
            + " WHERE "
            + " AND ".join(terms)
        )
    return " ".join(clauses), vertices


class UUIDGraphClient(GraphClient):
    def check_version(self, budget: PathBudget) -> None:
        rows = self.execute(
            'FETCH PROP ON projection_meta "meta:projection" YIELD properties(vertex) AS meta',
            budget,
            1,
        )
        if len(rows) != 1 or rows[0]["meta"] != meta_properties(self.manifest):
            raise QueryError("GRAPH_VERSION_MISMATCH", "UUID 图快照未完成或与 SQL 不一致", 409)


class MaterializedReader:
    def __init__(
        self,
        sql: PathReader | None,
        client: UUIDGraphClient,
        budget: PathBudget,
        person_lookup: Callable[[list[str]], list[Person]] | None = None,
        cache: RelationCache | None = None,
    ) -> None:
        self.sql, self.client, self.budget = sql, client, budget
        self.person_lookup = person_lookup
        self.cache = cache
        self._indexes = current_fact_indexes() or FactIndexes()
        manifest = getattr(client, "manifest", None)
        self._namespace = (
            id(client),
            *(
                getattr(manifest, field, None)
                for field in (
                    "space",
                    "projection_id",
                    "source_digest",
                    "data_version",
                    "reference_month",
                )
            ),
        )

    def persons(self, ids: list[str]) -> dict[str, Person]:
        if self.person_lookup is not None:
            self.budget.check()
            people = {person.id: person for person in self.person_lookup(ids)}
            self.budget.check()
            return people
        if self.sql is None:
            raise RuntimeError("SQL reader required for person details")
        return self.sql.persons(ids)

    def fact_views_by_ids(self, ids: list[str]) -> list[FactView]:
        if self.sql is None:
            raise RuntimeError("SQL reader required for fact details")
        return self.sql.fact_views_by_ids(ids)

    def shortest_connections(
        self, reference: str, candidates: list[str], request: SearchRequest
    ) -> dict[str, list[str]]:
        if self.cache is None:
            return self._shortest_connections(reference, candidates, request)
        return self.cache.get_or_compute(
            ["chains", reference, sorted(candidates), relation_scope_key(request)],
            self.budget,
            lambda: self._shortest_connections(reference, candidates, request),
        )

    def _shortest_connections(
        self, reference: str, candidates: list[str], request: SearchRequest
    ) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for hops in range(1, request.max_hops + 1):
            pending = sorted(set(candidates) - found.keys())
            if not pending:
                break
            statement, vertices = connection_match(reference, request, hops)
            sequence = f"connection_ids+[id({vertices[-1]})]" if hops > 1 else "[id(v0),id(v1)]"
            rows = self.client.execute(
                statement
                + f" AND id(v{hops}) IN {literal(pending)}"
                + f" RETURN id(v{hops}) AS person_id,min({sequence}) AS person_ids"
                + " ORDER BY person_id",
                self.budget,
                len(pending),
            )
            for row in rows:
                ids = row["person_ids"]
                if (
                    row["person_id"] not in pending
                    or len(ids) != hops + 1
                    or ids[0] != reference
                    or ids[-1] != row["person_id"]
                    or len(set(ids)) != len(ids)
                ):
                    raise QueryError("GRAPH_INTEGRITY", "图连接链端点或长度异常", 503)
                found[row["person_id"]] = ids
        return found

    def paths(self, request: PathRequest) -> list[str]:
        pattern = "|".join(kinds(request.scope))
        conditions = [
            f"id(a)=={literal(request.reference_id)}",
            f"id(b)=={literal(request.candidate_id)}",
            "id(m)!=id(a)",
            "id(m)!=id(b)",
            edge_filter("x", request.scope),
            edge_filter("y", request.scope),
        ]
        if request.intermediate_source:
            conditions.append(f"m.person.source_system=={literal(request.intermediate_source)}")
        limit = min(request.limits.path_limit, request.limits.candidate_limit)
        rows = self.client.execute(
            f"MATCH (a:person)-[x:{pattern}]-(m:person)-[y:{pattern}]-(b:person)"
            + school_requirement(request.scope, "a", "m")
            + school_requirement(request.scope, "m", "b")
            + " WHERE "
            + " AND ".join(conditions)
            + f" RETURN DISTINCT id(m) AS middle ORDER BY middle LIMIT {limit + 1}",
            self.budget,
            limit + 1,
        )
        if len(rows) > limit:
            self.budget.candidate_reasons.add(
                "path_limit" if limit == request.limits.path_limit else "candidate_limit"
            )
        result = [r["middle"] for r in rows[:limit]]
        self.budget.graph_candidates = len(result)
        return result

    def proofs(self, request: PathRequest, pairs: list[tuple[str, str]]) -> list[GraphProof]:
        return self.read_proofs(request.scope, pairs, request.limits.evidence_limit + 1)

    def read_proofs(
        self, scope: RelationScope, pairs: list[tuple[str, str]], per_kind_limit: int = 1001
    ) -> list[GraphProof]:
        if not pairs or len(pairs) > 50:
            raise ValueError("Expected 1–50 person pairs")
        try:
            return self._read_proofs(scope, pairs, per_kind_limit)
        except (KeyError, TypeError, ValueError):
            raise QueryError("GRAPH_INTEGRITY", "图人物关系或事实属性格式异常", 503) from None

    def _read_proofs(
        self, scope: RelationScope, pairs: list[tuple[str, str]], per_kind_limit: int
    ) -> list[GraphProof]:
        result = self._relation_rows(scope, pairs, per_kind_limit)
        # The subset edge replaces its matching same-company summary, not its other facts.
        overlap_keys = {
            (r["left_person"], r["right_person"], r["entity_vid"], r["left_rank"], r["right_rank"])
            for r in result
            if r["kind"] == "company_overlap"
        }
        result = [
            r
            for r in result
            if r["kind"] != "same_company"
            or (
                r["left_person"],
                r["right_person"],
                r["entity_vid"],
                r["left_rank"],
                r["right_rank"],
            )
            not in overlap_keys
        ]
        details = self._facts(result)
        proofs = []
        for r in result:
            self.budget.check()
            start_month, end_month = r.get("lo"), r.get("hi")
            months = (
                (end_month // 100 - start_month // 100) * 12
                + end_month % 100
                - start_month % 100
                + 1
                if start_month is not None and end_month is not None
                else None
            )
            proofs.append(
                GraphProof(
                    left_person=r["left_person"],
                    right_person=r["right_person"],
                    entity_id=r["entity_vid"][2:],
                    left_fact=f"slot:{r['left_rank']}",
                    right_fact=f"slot:{r['right_rank']}",
                    kind=cast(RelationType, KINDS[r["kind"]]),
                    start_month=start_month,
                    end_month=end_month,
                    months=months,
                    left_properties=details[
                        (r["left_person"], r["entity_vid"], FACTS[r["kind"]], r["left_rank"])
                    ],
                    right_properties=details[
                        (r["right_person"], r["entity_vid"], FACTS[r["kind"]], r["right_rank"])
                    ],
                )
            )
        return proofs

    def _relation_rows(
        self, scope: RelationScope, pairs: list[tuple[str, str]], limit: int
    ) -> list[dict]:
        result = []
        for kind in kinds(scope):
            maximum = PROOF_PAIR_BATCH if limit <= 21 else 8
            for batch in proof_batches(kind, scope, pairs, limit, maximum):
                # Each UNION branch keeps its own ORDER/LIMIT and overflow probe.
                statement = " UNION ALL ".join(
                    proof_query(kind, scope, left, right, limit) for left, right in batch
                )
                rows = self.client.execute(statement, self.budget, len(batch) * limit)
                counts = Counter((r["left_person"], r["right_person"]) for r in rows)
                if not set(counts).issubset(set(batch)) or any(n > limit for n in counts.values()):
                    raise QueryError("GRAPH_INTEGRITY", "批量图证据端点或配额异常", 503)
                if limit == 1001 and any(n == limit for n in counts.values()):
                    raise QueryError(
                        "EVIDENCE_LIMIT", "共同经历超过本地演练上限，请缩小关系范围", 422
                    )
                for row in rows:
                    if row["stored_source"] != row["left_person"]:
                        row["left_rank"], row["right_rank"] = row["right_rank"], row["left_rank"]
                    row["kind"] = kind
                result.extend(rows)
        return result

    def _facts(self, rows: list[dict]) -> dict[tuple, dict]:
        self.budget.check()
        keys = {
            (r[side + "_person"], r["entity_vid"], FACTS[r["kind"]], r[side + "_rank"])
            for r in rows
            for side in ("left", "right")
        }
        result = {
            key: self._indexes.graph[(self._namespace, key)]
            for key in keys
            if (self._namespace, key) in self._indexes.graph
        }
        observe("graph.fact_reused", len(result))
        missing = keys - result.keys()
        for edge in ("worked_at", "studied_at", "studied_major"):
            selected = sorted(k for k in missing if k[2] == edge)
            for offset in range(0, len(selected), 64):
                batch = selected[offset : offset + 64]
                refs = ",".join(f"{literal(p)}->{literal(e)}@{rank}" for p, e, _, rank in batch)
                found = self.client.execute(
                    f"FETCH PROP ON {edge} {refs} YIELD src(edge) AS source,"
                    "dst(edge) AS target,rank(edge) AS rank,properties(edge) AS props",
                    self.budget,
                    len(batch),
                )
                seen = set()
                for r in found:
                    key = (r["source"], r["target"], edge, r["rank"])
                    if key not in batch or key in seen:
                        raise QueryError("GRAPH_INTEGRITY", "图事实批次端点或排名异常", 503)
                    seen.add(key)
                    result[key] = fact_properties(edge, r["source"], r["rank"], r["props"])
        if set(result) != keys:
            raise QueryError("GRAPH_INTEGRITY", "人物边引用的事实缺失", 503)
        self.budget.check()
        for key in missing:
            self._indexes.graph[(self._namespace, key)] = result[key]
        return result


def proof_batches(
    kind: str, scope: RelationScope, pairs: list[tuple[str, str]], limit: int, maximum: int
) -> Iterator[list[tuple[str, str]]]:
    batch: list[tuple[str, str]] = []
    size = 0
    for pair in pairs:
        length = len(proof_query(kind, scope, *pair, limit).encode()) + len(" UNION ALL ")
        if length > 48 * 1024:
            raise QueryError("GRAPH_QUERY_LIMIT", "图取证语句超过读取边界，请缩小范围", 503)
        if batch and (len(batch) >= maximum or size + length > 48 * 1024):
            yield batch
            batch, size = [], 0
        batch.append(pair)
        size += length
    if batch:
        yield batch


def proof_query(kind: str, scope: RelationScope, left: str, right: str, limit: int) -> str:
    statement = (
        f"MATCH (a:person)-[r:{kind}]-(b:person)"
        + school_requirement(scope, "a", "b")
        + f" WHERE id(a)=={literal(left)} AND id(b)=={literal(right)} AND "
        + edge_filter("r", scope)
    )
    columns = (
        "id(a) AS left_person,id(b) AS right_person,src(r) AS stored_source,"
        "r.entity_vid AS entity_vid,r.left_fact_rank AS left_rank,"
        "r.right_fact_rank AS right_rank"
    )
    if kind == "company_overlap":
        lo, hi = "r.overlap_start_month", "r.overlap_end_month"
        if scope.relation_start_month:
            lo = (
                f"CASE WHEN {lo}>={scope.relation_start_month} "
                f"THEN {lo} ELSE {scope.relation_start_month} END"
            )
        if scope.relation_end_month:
            hi = (
                f"CASE WHEN {hi}<={scope.relation_end_month} "
                f"THEN {hi} ELSE {scope.relation_end_month} END"
            )
        columns += f",{lo} AS lo,{hi} AS hi"
    return (
        statement
        + (" RETURN DISTINCT " if scope.require_same_school else " RETURN ")
        + columns
        + f" ORDER BY entity_vid,left_rank,right_rank LIMIT {limit}"
    )


def fact_properties(edge: str, person: str, rank: int, props: dict) -> dict:
    common = {"experience_key", "start_month", "end_month"}
    expected = common | (
        {"position_title", "is_current"}
        if edge == "worked_at"
        else {"education_level", "is_regular_enrollment"}
    )
    if set(props) != expected:
        raise QueryError("GRAPH_INTEGRITY", "图经历属性集合与 DDL 不一致", 503)
    kind = {"worked_at": "employment", "studied_at": "education", "studied_major": "major"}[edge]
    source = person.split(":")[1]
    prefix, table, raw_id = props["experience_key"].split(":")
    if prefix != source or not raw_id.isdigit():
        raise QueryError("GRAPH_INTEGRITY", "图经历定位格式不正确", 503)
    return dict(
        fact_id=f"slot:{rank}",
        kind=kind,
        active=True,
        role_id=None,
        start_month=props["start_month"],
        end_month=props["end_month"],
        is_current=props.get("is_current", False),
        source_system=source,
        source_record_id=f"{table}:{raw_id}",
        experience_key=props["experience_key"],
        position_title=props.get("position_title"),
        education_level=props.get("education_level"),
        is_regular_enrollment=props.get("is_regular_enrollment"),
    )


class MaterializedGraphRepository:
    def __init__(self, source: SQLRepository, sql: PathRepository, client: UUIDGraphClient) -> None:
        self.source, self.manifest = source, client.manifest
        self.version, self.reference_month = source.version, source.reference_month
        self.sql, self.client = sql, client
        self.cache = client.relation_cache
        self.client.check_version(PathBudget(3000, 5000))

    def session(self, budget: PathBudget) -> AbstractContextManager[PathReader]:
        return self.sql.session(budget)

    @contextmanager
    def graph_session(self, budget: PathBudget) -> Iterator[MaterializedReader]:
        with self.sql.session(budget) as sql:
            self.client.check_version(budget)
            lookup = (
                self.source.persons
                if getattr(self.source, "person_display", "") == "mysql-live"
                else None
            )
            yield MaterializedReader(sql, self.client, budget, lookup, self.cache)
            self.client.check_version(budget)

    @contextmanager
    def candidate_session(self, budget: PathBudget) -> Iterator[None]:
        try:
            self.client.check_version(budget)
            yield
            self.client.check_version(budget)
        except PathBudgetExceeded as error:
            raise QueryError(
                "GRAPH_QUERY_LIMIT", f"关联人物查询达到图预算（{error.label}），请缩小范围", 503
            ) from None

    def shortest_connections(
        self, reference: str, candidates: list[str], request: SearchRequest, budget: PathBudget
    ) -> dict[str, list[str]]:
        # 稳定链只读图ID，不应在图引擎展开期间占用SQL连接。
        with self.candidate_session(budget):
            return MaterializedReader(
                None, self.client, budget, cache=self.cache
            ).shortest_connections(reference, candidates, request)

    def neighbor_block(
        self,
        reference: str,
        scope: RelationScope,
        after: str | None,
        budget: PathBudget,
        size: int = 128,
    ) -> NeighborBlock:
        if not 1 <= size <= 128:
            raise ValueError("候选块大小必须在1至128之间")
        arguments = ["neighbor-blocks-v1", reference, relation_scope_key(scope), size]
        cached = self.cache.covering(arguments, after, budget)
        if cached is not None:
            block = NeighborBlock.model_validate(cached)
            return block.model_copy(
                update={"ids": tuple(key for key in block.ids if not after or key > after)}
            )
        ids = self._neighbor_ids(reference, scope, after, budget, size)
        if ids != sorted(set(ids)) or len(ids) > size + 1 or (after and ids and ids[0] <= after):
            raise QueryError("GRAPH_INTEGRITY", "关联人物游标顺序异常", 503)
        block = NeighborBlock(ids=tuple(ids[:size]), has_more=len(ids) > size)
        self.cache.store_range(
            arguments,
            after,
            block.ids[-1] if block.ids else after or "",
            not block.has_more,
            block.model_dump(mode="json"),
            budget,
        )
        return block

    def _neighbor_ids(
        self,
        reference: str,
        scope: RelationScope,
        after: str | None,
        budget: PathBudget,
        size: int,
    ) -> list[str]:
        if isinstance(scope, SearchRequest) and scope.max_hops > 1:
            if not scope.require_same_school:
                return self._traversal_page(reference, scope, after, budget, size)
            found: set[str] = set()
            for hops in range(1, scope.max_hops + 1):
                statement, _ = connection_match(reference, scope, hops, paths=False)
                if after is not None:
                    statement += f" AND id(v{hops})>{literal(after)}"
                rows = self.client.execute(
                    statement
                    + f" RETURN DISTINCT id(v{hops}) AS person_id"
                    + f" ORDER BY person_id LIMIT {size + 1}",
                    budget,
                    size + 1,
                )
                found.update(row["person_id"] for row in rows)
            return sorted(found)[: size + 1]
        pattern = "|".join(kinds(scope))
        condition = edge_filter("r", scope)
        if after:
            condition += f" AND id(b)>{literal(after)}"
        rows = self.client.execute(
            f"MATCH (a:person)-[r:{pattern}]-(b:person)"
            + school_requirement(scope, "a", "b")
            + f" WHERE id(a)=={literal(reference)} AND "
            + condition
            + f" RETURN DISTINCT id(b) AS person_id ORDER BY person_id LIMIT {size + 1}",
            budget,
            size + 1,
        )
        return [row["person_id"] for row in rows]

    def _traversal_page(
        self,
        reference: str,
        scope: SearchRequest,
        after: str | None,
        budget: PathBudget,
        size: int,
    ) -> list[str]:
        # 原生GO每步按顶点遍历，返回终点集合，避免多跳MATCH携带所有路径状态。
        condition = f"$-.person_id!={literal(reference)}"
        if after is not None:
            condition += f" AND $-.person_id>{literal(after)}"
        statement = (
            f"GO 1 TO {scope.max_hops} STEPS FROM {literal(reference)} "
            f"OVER {','.join(kinds(scope))} BIDIRECT "
            f"WHERE {edge_filter('properties(edge)', scope)} "
            "YIELD DISTINCT id($$) AS person_id | "
            "YIELD DISTINCT $-.person_id AS person_id WHERE "
            + condition
            + f" | ORDER BY $-.person_id | LIMIT {size + 1}"
        )
        rows = self.client.execute(statement, budget, size + 1)
        return [row["person_id"] for row in rows]

    def connected(self, reference: str, candidate: str, scope: RelationScope) -> bool:
        budget = PathBudget(3000, 5000)
        with self.candidate_session(budget):
            pattern = "|".join(kinds(scope))
            rows = self.client.execute(
                f"MATCH (a:person)-[r:{pattern}]-(b:person) "
                + school_requirement(scope, "a", "b")
                + f" WHERE id(a)=={literal(reference)} AND id(b)=={literal(candidate)} AND "
                + edge_filter("r", scope)
                + " RETURN id(b) AS person_id LIMIT 1",
                budget,
                1,
            )
            return bool(rows)


class UUIDGraphRepository(MaterializedGraphRepository):
    def __init__(self, source: UUIDRepository, manifest_path: Path) -> None:
        sql = MySQLPathRepository(
            source.engine,
            source.version,
            source.reference_month,
            tables=source.tables,
            verify=source.verify_connection,
        )
        client = UUIDGraphClient(source.manifest, read_reader(manifest_path))
        try:
            super().__init__(source, sql, client)
        except BaseException:
            client.close()
            raise
