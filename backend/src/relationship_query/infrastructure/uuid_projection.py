"""新 UUID 空间构建与完整回读。关系由 nGQL 计算；未完整核对不能 ready。"""

from collections import Counter
from pathlib import Path
from typing import Any

from relationship_query.infrastructure.graph_model import literal
from relationship_query.infrastructure.graph_projection import ProjectionWriter
from relationship_query.infrastructure.nebula_lab import query
from relationship_query.infrastructure.source_read_model import source_digest
from relationship_query.infrastructure.uuid_source import FACT_TYPES, MODEL
from relationship_query.runtime.diagnostics import stage

RELATIONS = {
    "same_company": ("worked_at", "company"),
    "company_overlap": ("worked_at", "company"),
    "same_school": ("studied_at", "school"),
    "same_major": ("studied_major", "major"),
}
MAX_RELATIONS = 10_000


def schema_statements(root: Path) -> list[str]:
    statements = []
    for name in ("uuid-facts-v3.ngql", "person-relations-v3.ngql"):
        text = "\n".join(
            line
            for line in (root / "infra/nebula/schema" / name).read_text().splitlines()
            if not line.lstrip().startswith("--")
        )
        for statement in text.split(";"):
            if statement.strip():
                if not statement.strip().startswith(("CREATE TAG ", "CREATE EDGE ")):
                    raise ValueError("Only fixed graph DDL is allowed")
                statements.append(statement.strip())
    return statements


def estimate(edges: list[dict]) -> int:
    counts = Counter((e["type"], e["target"]) for e in edges)
    # Includes repeated facts and overestimates same-person pairs, deliberately conservative.
    return sum(
        n * (n - 1) // 2 * (2 if kind == "worked_at" else 1) for (kind, _), n in counts.items()
    )


def relation_query(kind: str, entity: str, reference_month: int, limit: int) -> str:
    fact, tag = RELATIONS[kind]
    start = (
        f"MATCH (a:person)-[l:{fact}]->(e:{tag})<-[r:{fact}]-(b:person) "
        f"WHERE id(e)=={literal(entity)} AND id(a)<id(b) "
    )
    columns = (
        "id(a) AS source,id(b) AS target,id(e) AS entity_vid,"
        "rank(l) AS left_fact_rank,rank(r) AS right_fact_rank"
    )
    if kind == "company_overlap":
        start += (
            f"WITH a,b,e,l,r,CASE WHEN l.is_current THEN {reference_month} "
            "ELSE l.end_month END AS le,"
            f"CASE WHEN r.is_current THEN {reference_month} ELSE r.end_month END AS re "
            "WHERE l.start_month IS NOT NULL AND r.start_month IS NOT NULL "
            "AND le IS NOT NULL AND re IS NOT NULL AND l.start_month<=le "
            "AND r.start_month<=re AND l.start_month<=re AND r.start_month<=le "
        )
        columns += (
            ",CASE WHEN l.start_month>=r.start_month THEN l.start_month "
            "ELSE r.start_month END AS overlap_start_month,"
            "CASE WHEN le<=re THEN le ELSE re END AS overlap_end_month"
        )
    return (
        start
        + "RETURN DISTINCT "
        + columns
        + f" ORDER BY source,target,entity_vid,left_fact_rank,right_fact_rank LIMIT {limit}"
    )


def calculate_relations(
    session: Any, nodes: list[dict], reference_month: int, *, max_relations: int = MAX_RELATIONS
) -> list[dict]:
    if max_relations < 1:
        raise ValueError("Relationship budget must be positive")
    rows: list[dict] = []
    for kind, (_, tag) in RELATIONS.items():
        for node in nodes:
            if node["type"] != tag:
                continue
            selected = query(
                session,
                relation_query(kind, node["vid"], reference_month, max_relations - len(rows) + 1),
            )
            if len(rows) + len(selected) > max_relations:
                raise ValueError("RELATION_BUILD_LIMIT: incomplete graph will not be published")
            for item in selected:
                rows.append(
                    dict(
                        source=item.pop("source"),
                        target=item.pop("target"),
                        type=kind,
                        properties=item,
                    )
                )
    with stage("Build.sort_relations"):
        rows.sort(
            key=lambda e: (
                e["type"],
                e["source"],
                e["target"],
                e["properties"]["entity_vid"],
                e["properties"]["left_fact_rank"],
                e["properties"]["right_fact_rank"],
            )
        )
    with stage("Build.rank_relations"):
        counters: Counter[tuple] = Counter()
        for row in rows:
            key = row["type"], row["source"], row["target"]
            counters[key] += 1
            row["rank"] = counters[key]
    return rows


def insert_nodes(writer: ProjectionWriter, nodes: list[dict]) -> None:
    for tag in ("person", "company", "school", "major"):
        selected = [n for n in nodes if n["type"] == tag]
        if selected:
            fields = list(selected[0]["properties"])
            writer.vertices(
                tag, fields, [(n["vid"], [n["properties"][f] for f in fields]) for n in selected]
            )


def insert_edges(writer: ProjectionWriter, edges: list[dict]) -> None:
    for kind in (*FACT_TYPES, *RELATIONS):
        selected = [e for e in edges if e["type"] == kind]
        if selected:
            fields = list(selected[0]["properties"])
            writer.edges(
                kind,
                fields,
                [
                    (e["source"], e["target"], e["rank"], [e["properties"][f] for f in fields])
                    for e in selected
                ],
            )


def read_all(
    execute: Any, nodes: list[dict], *, max_rows_per_query: int = MAX_RELATIONS
) -> tuple[list[dict], list[dict]]:
    """execute must enforce a per-query row bound; no unbounded graph scans."""
    actual_nodes: list[dict] = []
    actual_edges: list[dict] = []
    for tag in ("person", "company", "school", "major"):
        selected = [n["vid"] for n in nodes if n["type"] == tag]
        for offset in range(0, len(selected), 32):
            ids = ",".join(literal(i) for i in selected[offset : offset + 32])
            found = execute(
                f"FETCH PROP ON {tag} {ids} YIELD id(vertex) AS vid,"
                "properties(vertex) AS properties",
                32,
            )
            actual_nodes.extend(dict(**r, type=tag) for r in found)
    people = [n["vid"] for n in nodes if n["type"] == "person"]
    for offset in range(0, len(people), 8):
        ids = ",".join(literal(i) for i in people[offset : offset + 8])
        for kind in (*FACT_TYPES, *RELATIONS):
            found = execute(
                f"GO FROM {ids} OVER {kind} YIELD src(edge) AS source,dst(edge) AS target,"
                f"rank(edge) AS rank,properties(edge) AS properties,{literal(kind)} AS type "
                f"LIMIT [{max_rows_per_query + 1}]",
                max_rows_per_query + 1,
            )
            if len(found) > max_rows_per_query:
                raise ValueError("Graph verification exceeds lab budget")
            actual_edges.extend(found)
    return actual_nodes, actual_edges


def graph_digest(nodes: list[dict], edges: list[dict]) -> str:
    return source_digest(
        dict(
            nodes=sorted(nodes, key=lambda n: n["vid"]),
            edges=sorted(edges, key=lambda e: (e["source"], e["target"], e["type"], e["rank"])),
        )
    )


def meta_properties(manifest: Any, state: str = "ready") -> dict:
    return dict(
        schema_version=MODEL,
        projection_id=manifest.projection_id,
        snapshot_sha256=manifest.source_digest,
        reference_month=manifest.reference_month,
        state=state,
    )
