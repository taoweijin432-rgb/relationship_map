"""将当前冻结虚构数据迁移至 UUID SQL／新图空间；绝不覆盖已有库、空间或清单。"""

import argparse
import json
import secrets
import shlex
from collections import Counter
from pathlib import Path
from time import perf_counter

from handoff_lab import create_lab
from projection_source_lab import raw_statements, save
from relationship_query.infrastructure.graph_projection import (
    ProjectionWriter,
    _reader_account,
)
from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
)
from relationship_query.infrastructure.projection_source_schema import (
    MAPPING as OLD_MAPPING,
)
from relationship_query.infrastructure.projection_source_schema import (
    PREFIX,
    SLOTS,
)
from relationship_query.infrastructure.projection_source_trial import (
    open_projection_engine,
)
from relationship_query.infrastructure.source_api import SourceRepository
from relationship_query.infrastructure.source_read_model import snapshot, source_digest
from relationship_query.infrastructure.source_releases import read_bundle
from relationship_query.infrastructure.uuid_projection import (
    calculate_relations,
    estimate,
    graph_digest,
    insert_edges,
    insert_nodes,
    meta_properties,
    read_all,
    schema_statements,
)
from relationship_query.infrastructure.uuid_source import (
    ENTITY_TAGS,
    FACT_TYPES,
    MAPPING,
    MODEL,
    NAMES,
    UUIDManifest,
    mock_schema,
    projection_records,
    reflect,
)
from sqlalchemy import insert

ROOT = Path(__file__).resolve().parents[1]


def migrate_rows(old: dict, bridge: list[dict], normalized: dict) -> dict:
    """消费已有明确的历史 UUID 对照，不从名称猜测，不维护新实体字典。"""
    rows = {
        name: old[name]
        for p in PREFIX.values()
        for name in (p, *(f"{p}_{s}" for s in SLOTS))
    }
    targets = {}
    for table, (tag, _) in ENTITY_TAGS.items():
        rows[table] = []
        for b in bridge:
            if b["source_table"] != f"graph_{tag}":
                continue
            entity = next(
                r for r in normalized[f"graph_{tag}"] if r["id"] == b["source_uuid"]
            )
            rows[table].append(
                dict(
                    id=entity["id"],
                    standard_name=entity["standard_name"],
                    **{f"{tag}_code": entity[f"{tag}_code"]},
                    is_deleted=int(entity["is_deleted"]),
                )
            )
            if b["entity_id"] in targets:
                raise ValueError("Ambiguous historical crosswalk")
            targets[b["entity_id"]] = entity["id"]
    rows[MAPPING] = []
    for m in old[OLD_MAPPING]:
        if m["edge_type"] not in FACT_TYPES:
            continue
        rows[MAPPING].append(
            {
                **{k: v for k, v in m.items() if k != "entity_id"},
                "standard_entity_id": targets[m["entity_id"]],
            }
        )
    return rows


def run(bundle_path: Path, bridge: Path, normalized: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("Use a new output directory")
    started = perf_counter()
    bundle = read_bundle(bundle_path)
    old_engine = open_projection_engine(bundle.mysql_url)
    try:
        source = SourceRepository(old_engine, bundle.manifest)
        with old_engine.connect() as c:
            old = snapshot(c, source.source_schema)
        rows = migrate_rows(
            old, json.loads(bridge.read_text()), json.loads(normalized.read_text())
        )
        nodes, facts = projection_records(rows, bundle.manifest.reference_month)
        upper_bound = estimate(facts)
        if upper_bound > 10_000:
            raise ValueError(
                "Relationship pair estimate exceeds lab budget, nothing created"
            )
        output.mkdir(parents=True, exist_ok=False)
        save(
            output / "migration-inputs.json",
            dict(
                old_bundle=str(bundle_path.resolve()),
                old_source_digest=bundle.manifest.source_digest,
                bridge_sha256=source_digest(json.loads(bridge.read_text())),
                normalized_sha256=source_digest(json.loads(normalized.read_text())),
                omitted_old_edge_types=[
                    "held_role",
                    "participated_in",
                    "collaborated with",
                ],
                warning=(
                    "Legacy UUID crosswalk is migration input only; "
                    "no independent dictionary is restored"
                ),
            ),
        )
        url, version = create_lab()
        engine = open_projection_engine(url, writable=True)
        try:
            with engine.connect() as c:
                for statement in raw_statements():
                    c.exec_driver_sql(statement)
            mock_schema().create_all(engine, checkfirst=False)
            schema = reflect(engine)
            with engine.begin() as c:
                for table in schema.sorted_tables:
                    if rows[table.name]:
                        c.execute(insert(table), rows[table.name])
            with engine.connect() as c:
                frozen = snapshot(c, schema, NAMES)
        finally:
            engine.dispose()
        nodes, facts = projection_records(frozen, bundle.manifest.reference_month)
        digest = source_digest(frozen)
        projection = f"uuid-v5-{digest[:20]}-{bundle.manifest.reference_month}"
        space = "relationship_lab_uuid_" + secrets.token_hex(6)
        # No ready manifest is written until full graph and read-only access verification succeeds.
        with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
            query(
                session,
                f"CREATE SPACE `{space}` "
                "(partition_num=1,replica_factor=1,vid_type=FIXED_STRING(128))",
            )
            query(session, f"USE `{space}`", wait=True)
            for ddl in schema_statements(ROOT):
                query(session, ddl, wait=True)
            provisional = UUIDManifest(
                source_database=engine.url.database,
                space=space,
                projection_id=projection,
                data_version=projection,
                reference_month=bundle.manifest.reference_month,
                source_digest=digest,
                counts={},
                graph_digest="0" * 64,
            )
            writer = ProjectionWriter(session)
            props = meta_properties(provisional, "staging")
            writer.vertices(
                "projection_meta",
                list(props),
                [("meta:projection", list(props.values()))],
            )
            insert_nodes(writer, nodes)
            insert_edges(writer, facts)
            relations = calculate_relations(session, nodes, provisional.reference_month)
            insert_edges(writer, relations)
            expected_digest = graph_digest(nodes, facts + relations)

            def execute(statement: str, limit: int) -> list[dict]:
                found = query(session, statement)
                if len(found) > limit:
                    raise ValueError("Verification result limit exceeded")
                return found

            actual_nodes, actual_edges = read_all(execute, nodes)
            if graph_digest(actual_nodes, actual_edges) != expected_digest:
                raise ValueError("Complete graph readback mismatch; remains staging")
            credentials = _reader_account(session, output)
            query(session, f"GRANT ROLE GUEST ON `{space}` TO {credentials.username}")
            counts = {name: len(values) for name, values in frozen.items()}
            counts.update(
                {
                    "graph_nodes": len(nodes),
                    "graph_facts": len(facts),
                    **Counter(e["type"] for e in relations),
                }
            )
            manifest = provisional.model_copy(
                update=dict(counts=counts, graph_digest=expected_digest)
            )
            props = meta_properties(manifest)
            writer.vertices(
                "projection_meta",
                list(props),
                [("meta:projection", list(props.values()))],
            )
        save(output / "source-snapshot.json", frozen)
        save(output / "graph-nodes.json", nodes)
        save(output / "graph-edges.json", facts + relations)
        save(output / "manifest.json", manifest.model_dump(mode="json"))
        config = output / "api.env"
        config.touch(mode=0o600, exist_ok=False)
        config.write_text(
            "export RELATIONSHIP_SOURCE_API_MANIFEST="
            + shlex.quote(str((output / "manifest.json").resolve()))
            + "\nexport RELATIONSHIP_SOURCE_API_MYSQL_URL="
            + shlex.quote(url)
            + "\n"
        )
        from relationship_query.infrastructure.uuid_verification import (
            verify_bundle_graph,
        )

        try:
            verify_bundle_graph(output)
            source.verify_snapshot()
        except Exception:
            # Only remove this attempt's publication pointer; failed resources remain inspectable.
            (output / "manifest.json").unlink(missing_ok=True)
            raise
        report = dict(
            model=MODEL,
            status="verified",
            data_mode="mock",
            source_database=manifest.source_database,
            space=space,
            counts=counts,
            pair_upper_bound=upper_bound,
            mysql_version=version,
            old_source_unchanged=True,
            cloud_access=False,
            graph_digest=expected_digest,
            elapsed_seconds=round(perf_counter() - started, 3),
        )
        save(output / "report.json", report)
        return report
    finally:
        old_engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-bundle", type=Path, required=True)
    p.add_argument("--bridge", type=Path, required=True)
    p.add_argument("--normalized", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(
        json.dumps(
            run(a.source_bundle, a.bridge, a.normalized, a.output),
            ensure_ascii=False,
            indent=2,
        )
    )
