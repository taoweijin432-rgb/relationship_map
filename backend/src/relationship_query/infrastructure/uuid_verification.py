"""发布／切换前核对新模型的完整允许属性、SQL 摘要和图摘要。"""

from pathlib import Path

from relationship_query.infrastructure.graph_model import read_reader
from relationship_query.infrastructure.nebula_lab import query
from relationship_query.infrastructure.projection_source_graph import reader_session
from relationship_query.infrastructure.source_api import open_source_engine
from relationship_query.infrastructure.source_read_model import snapshot
from relationship_query.infrastructure.uuid_api import UUIDRepository
from relationship_query.infrastructure.uuid_projection import (
    graph_digest,
    meta_properties,
    read_all,
)
from relationship_query.infrastructure.uuid_source import NAMES, UUIDManifest, projection_records


def verify_bundle_graph(directory: Path) -> None:
    from relationship_query.infrastructure.source_releases import read_bundle

    bundle = read_bundle(directory)
    if not isinstance(bundle.manifest, UUIDManifest):
        raise ValueError("Not a UUID graph manifest")
    engine = open_source_engine(bundle.mysql_url, bundle.manifest, directory / "manifest.json")
    try:
        source = UUIDRepository(engine, bundle.manifest)
        with engine.connect() as connection:
            nodes, facts = projection_records(
                snapshot(connection, source.source_schema, NAMES), source.reference_month
            )
        with reader_session(read_reader(directory / "manifest.json")) as reader:
            query(reader, f"USE `{bundle.manifest.space}`")

            def execute(statement: str, maximum: int) -> list[dict]:
                rows = query(reader, statement)
                if len(rows) > maximum:
                    raise ValueError("UUID verification limit exceeded")
                return rows

            meta = query(
                reader,
                'FETCH PROP ON projection_meta "meta:projection" YIELD properties(vertex) AS meta',
            )
            if meta != [{"meta": meta_properties(bundle.manifest)}]:
                raise ValueError("UUID projection is not ready")
            actual_nodes, actual_edges = read_all(execute, nodes)
            if graph_digest(actual_nodes, actual_edges) != bundle.manifest.graph_digest:
                raise ValueError("UUID graph full digest mismatch")
            actual_facts = [
                e for e in actual_edges if e["type"] in {"worked_at", "studied_at", "studied_major"}
            ]
            if graph_digest(actual_nodes, actual_facts) != graph_digest(nodes, facts):
                raise ValueError("UUID graph differs from frozen SQL facts")
            columns = query(reader, "DESCRIBE TAG person")
            if {r["Field"] for r in columns} != {"source_system", "serial_number"}:
                raise ValueError("Person privacy schema mismatch")
        source.verify_snapshot()
    finally:
        engine.dispose()
