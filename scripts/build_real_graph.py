"""将已冻结的真实跨库输入构建为独立Nebula图，并用SQL事实独立核对人物边。"""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from time import perf_counter

from relationship_query.infrastructure.member_index import (
    build_member_index as write_member_index,
)
from relationship_query.infrastructure.member_index import (
    index_binding,
)
from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
)
from relationship_query.infrastructure.numeric_read_model import write_query_model
from relationship_query.infrastructure.uuid_projection import estimate, graph_digest, read_all
from relationship_query.update.artifacts import checksum, source_sqlite, write_json
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import Projection, digest, encode
from relationship_query.update.projection import NumericProjectionAdapter
from relationship_query.update.real_input import ENTITY_TABLES, PERSON_TABLES, prepare_rows
from relationship_query.update.target import BuildContext, NebulaTarget

ROOT = Path(__file__).resolve().parents[1]


def real_contract(entities: dict, people: dict) -> SourceContract:
    contract_file = ROOT / "resources/examples/update-authoritative-contract-v1.json"
    data = json.loads(contract_file.read_text())
    data.update(version="real-split-mysql-v2", adapter="numeric-authoritative-v2")
    for logical, binding in data["tables"].items():
        source = entities if logical in ENTITY_TABLES else people
        table = (ENTITY_TABLES | PERSON_TABLES)[logical]
        binding["physical"] = source["metadata"]["database"] + "." + table
    for name in ("person_expert", "person_resume"):
        data["tables"][name]["columns"].update(city="city", headline="job_name")
    if any("former_names" in row for row in entities["tables"][ENTITY_TABLES["school"]]):
        data["tables"]["school"]["columns"]["former_names"] = "former_names"
    data["entity_statuses"] = {kind: ["已核验"] for kind in ("company", "school", "major")}
    data["inactive_entity_statuses"] = {kind: ["已合并"] for kind in ("company", "school", "major")}
    # 只有来源1确认当前任职。来源0保留原值，缺少截止日期时不会获得同期证据。
    data.update(current_values=[1], past_values=[0, 2])
    return SourceContract.model_validate(data)


def prepare(source: Path, output: Path, reference_month: int) -> dict:
    entities = json.loads((source / "entity-source.json").read_text())
    people = json.loads((source / "person-source.json").read_text())
    contract = real_contract(entities, people)
    rows, audit = prepare_rows(entities, people, contract)
    projection = NumericProjectionAdapter(contract).build(rows, reference_month)
    version = f"real-{digest(rows)[:20]}-{reference_month}"
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    write_json(output / "contract.json", contract.model_dump(mode="json"))
    write_json(output / "source-snapshot.json", rows)
    write_json(output / "input-audit.json", audit)
    write_json(output / "graph-plan.json", projection.model_dump(mode="json"))
    source_sqlite(output / "source.sqlite", contract, rows)
    write_query_model(
        output / "source.sqlite", contract, rows, projection, version, reference_month
    )
    metadata = dict(
        format="real-graph-plan-v1",
        data_mode="real",
        version=version,
        source_digest=digest(rows),
        reference_month=reference_month,
        sources=[entities["metadata"], people["metadata"]],
        source_files={
            name: checksum(source / name) for name in ("entity-source.json", "person-source.json")
        },
        files={
            name: checksum(output / name)
            for name in (
                "contract.json",
                "source-snapshot.json",
                "input-audit.json",
                "source.sqlite",
                "graph-plan.json",
            )
        },
        nodes=dict(Counter(node["type"] for node in projection.nodes)),
        facts=dict(Counter(edge["type"] for edge in projection.facts)),
        relation_upper_bound=estimate(projection.facts),
        quarantine=dict(Counter(row["reason"] for row in audit["quarantine"])),
        zero_dates_to_null=len(audit["zero_dates_to_null"]),
        person_display=people.get("person_display", "snapshot"),
    )
    write_json(output / "prepared.json", metadata)
    return metadata


def proof_hash(records) -> str:
    result = hashlib.sha256()
    for record in records:
        result.update(encode(list(record)).encode())
        result.update(b"\n")
    return result.hexdigest()


def sql_proofs(connection: sqlite3.Connection, kind: str, month: int):
    fact_type = {"same_school": "education", "same_major": "major"}.get(kind, "employment")
    left_end = "CASE WHEN a.is_current=1 THEN :month ELSE a.end_month END"
    right_end = "CASE WHEN b.is_current=1 THEN :month ELSE b.end_month END"
    overlap = "NULL AS overlap_start,NULL AS overlap_end"
    conditions = ""
    if kind == "company_overlap":
        overlap = f"MAX(a.start_month,b.start_month),MIN({left_end},{right_end})"
        conditions = (
            f" AND a.start_month IS NOT NULL AND b.start_month IS NOT NULL"
            f" AND {left_end} IS NOT NULL AND {right_end} IS NOT NULL"
            f" AND a.start_month<={left_end} AND b.start_month<={right_end}"
            f" AND a.start_month<={right_end} AND b.start_month<={left_end}"
        )
    statement = (
        "SELECT DISTINCT a.person_id,b.person_id,'e:'||a.entity_id,"
        "CAST(SUBSTR(a.id,6) AS INTEGER),CAST(SUBSTR(b.id,6) AS INTEGER),"
        + overlap
        + " FROM demo_fact a JOIN demo_fact b ON a.entity_id=b.entity_id"
        " AND a.type=b.type AND a.person_id<b.person_id"
        " WHERE a.active=1 AND b.active=1 AND a.type=:type" + conditions + " ORDER BY 1,2,3,4,5"
    )
    return connection.execute(statement, {"month": month, "type": fact_type})


def verify_graph(output: Path, metadata: dict, receipt) -> dict:
    plan = json.loads((output / "graph-plan.json").read_text())
    bound = max(metadata["relation_upper_bound"], len(plan["facts"]), 1)
    with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
        query(session, f"USE `{receipt.space}`")

        def bounded(statement: str, maximum: int) -> list[dict]:
            records = query(session, statement)
            if len(records) > maximum:
                raise RuntimeError("原生图回读超出计划范围")
            return records

        nodes, edges = read_all(bounded, plan["nodes"], max_rows_per_query=bound)
    if graph_digest(nodes, edges) != receipt.graph_digest:
        raise RuntimeError("图摘要与构建收据不符")
    proofs = {}
    connection = sqlite3.connect((output / "source.sqlite").as_uri() + "?mode=ro", uri=True)
    try:
        for kind in ("same_company", "company_overlap", "same_school", "same_major"):
            actual = sorted(
                (
                    edge["source"],
                    edge["target"],
                    edge["properties"]["entity_vid"],
                    edge["properties"]["left_fact_rank"],
                    edge["properties"]["right_fact_rank"],
                    edge["properties"].get("overlap_start_month"),
                    edge["properties"].get("overlap_end_month"),
                )
                for edge in edges
                if edge["type"] == kind
            )
            expected = list(sql_proofs(connection, kind, metadata["reference_month"]))
            expected_hash, actual_hash = proof_hash(expected), proof_hash(actual)
            if expected_hash != actual_hash:
                raise RuntimeError(f"{kind}的全部图证据与独立SQL基准不符")
            proofs[kind] = {"count": len(actual), "proof_sha256": actual_hash}
    finally:
        connection.close()
    return {
        "passed": True,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "all_graph_rows_verified": True,
        "independent_sql_proofs": proofs,
    }


def build(output: Path, *, build_member_index: bool = False) -> dict:
    metadata = json.loads((output / "prepared.json").read_text())
    for name, expected in metadata["files"].items():
        if checksum(output / name) != expected:
            raise RuntimeError("已准备的真实输入文件发生变化")
    projection = Projection.model_validate_json((output / "graph-plan.json").read_text())
    directory = output / "graph"
    directory.mkdir(mode=0o700, exist_ok=False)
    context = BuildContext(
        directory, metadata["version"], metadata["source_digest"], metadata["reference_month"]
    )
    started = perf_counter()
    receipt = NebulaTarget(
        DEFAULT_CREDENTIALS, max_relations=max(1, metadata["relation_upper_bound"])
    ).build_and_verify(projection, context)
    write_json(output / "graph-receipt.json", receipt.model_dump(mode="json"))
    validation = verify_graph(output, metadata, receipt)
    manifest = dict(
        format="real-graph-build-v1",
        data_mode="real",
        state="verified",
        **{
            key: metadata[key] for key in ("version", "source_digest", "reference_month", "sources")
        },
        graph=receipt.model_dump(mode="json"),
        validation=validation,
        elapsed_seconds=round(perf_counter() - started, 3),
        person_display=metadata.get("person_display", "snapshot"),
    )
    if build_member_index:
        binding = index_binding(
            output,
            metadata["version"],
            metadata["source_digest"],
            metadata["reference_month"],
            receipt,
        )
        query_index = write_member_index(output, projection, binding)
        manifest["query_index"] = query_index.model_dump(mode="json")
        manifest["elapsed_seconds"] = round(perf_counter() - started, 3)
    write_json(output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-month", type=int, default=202611)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--build-prepared", action="store_true")
    parser.add_argument("--build-member-index", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.build_prepared:
        metadata = json.loads((output / "prepared.json").read_text())
    else:
        if args.input is None:
            parser.error("首次准备需要--input")
        metadata = prepare(args.input.resolve(), output, args.reference_month)
    print(
        json.dumps(
            {
                key: metadata[key]
                for key in (
                    "nodes",
                    "facts",
                    "relation_upper_bound",
                    "quarantine",
                    "zero_dates_to_null",
                )
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if not args.prepare_only:
        manifest = build(output, build_member_index=args.build_member_index)
        print(json.dumps(manifest, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
