"""使用真实图只读账号核对既有1至4跳查询及逐段事实回查。"""

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import cast

from sqlalchemy import create_engine

from relationship_query.contracts import SearchRequest
from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.graph_model import ReaderCredentials
from relationship_query.infrastructure.numeric_api import NumericGraphClient, NumericManifest
from relationship_query.infrastructure.numeric_read_model import query_schema
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.infrastructure.sqlite_paths import SQLitePathRepository
from relationship_query.infrastructure.uuid_graph import MaterializedGraphRepository
from relationship_query.update.artifacts import write_json


def expected_layers(path: Path) -> tuple[str, list[list[str]]]:
    adjacency = defaultdict(set)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT DISTINCT a.person_id,b.person_id FROM demo_fact a JOIN demo_fact b"
            " ON a.entity_id=b.entity_id AND a.person_id<b.person_id"
            " WHERE a.type='employment' AND b.type='employment'"
            " AND a.active=1 AND b.active=1"
        )
        for left, right in rows:
            adjacency[left].add(right)
            adjacency[right].add(left)
    # 选择真实小邻域，独立BFS仅作为验收基准，运行查询仍使用图内模板。
    for person in sorted(adjacency):
        if not 1 <= len(adjacency[person]) <= 3:
            continue
        seen, frontier, layers = {person}, {person}, []
        for _ in range(4):
            frontier = set().union(*(adjacency[node] for node in frontier)) - seen
            seen.update(frontier)
            layers.append(sorted(seen - {person}))
        if len(layers[3]) <= 80 and all(len(layers[i]) > len(layers[i - 1]) for i in (1, 2, 3)):
            return person, layers
    raise RuntimeError("真实输入中未找到适合四层完整验收的小邻域")


def verify(output: Path) -> dict:
    manifest = json.loads((output / "manifest.json").read_text())
    person, expected = expected_layers(output / "source.sqlite")
    engine = create_engine(f"sqlite:///file:{output / 'source.sqlite'}?mode=ro&uri=true")
    client = None
    try:
        _, tables = query_schema()
        source = SQLRepository(engine, tables=tables)
        graph_manifest = NumericManifest(
            space=manifest["graph"]["space"],
            projection_id=manifest["version"],
            data_version=source.version,
            reference_month=source.reference_month,
            source_digest=manifest["source_digest"],
            counts=cast(dict[str, int], source.counts()),
        )
        reader = ReaderCredentials.model_validate_json(
            (output / "graph/reader-credentials.json").read_text()
        )
        client = NumericGraphClient(graph_manifest, reader)
        paths = SQLitePathRepository(engine, source.version, source.reference_month, tables=tables)
        graph = MaterializedGraphRepository(source, paths, client)
        checks = []
        for depth in range(1, 5):
            request = SearchRequest(relation_type="same_company", max_hops=depth)
            budget = PathBudget(5000, 5000)
            started = perf_counter()
            with graph.candidate_session(budget):
                actual = graph.neighbor_page(person, request, None, budget)
            if actual != expected[depth - 1]:
                raise RuntimeError(f"真实图{depth}跳结果与独立SQL事实BFS不符")
            previous = set(expected[depth - 2]) if depth > 1 else set()
            candidate = min(set(actual) - previous)
            with graph.graph_session(budget) as reader_session:
                connection = reader_session.shortest_connections(person, [candidate], request)[
                    candidate
                ]
                views = reader_session.fact_views_by_ids(
                    [view.fact.id for view in source.fact_views(connection)]
                )
            if not views or len(connection) != depth + 1:
                raise RuntimeError("真实连接链或SQL事实定位失败")
            companies = {
                identity: {
                    view.fact.entity_id
                    for view in views
                    if view.fact.person_id == identity and view.fact.type == "employment"
                }
                for identity in connection
            }
            if any(
                not companies[left] & companies[right]
                for left, right in zip(connection, connection[1:])
            ):
                raise RuntimeError("连接链段落缺少对应的SQL公司经历")
            checks.append(
                {
                    "max_hops": depth,
                    "candidate_count": len(actual),
                    "sample_connection": connection,
                    "sql_fact_count": len(views),
                    "elapsed_ms": round((perf_counter() - started) * 1000, 3),
                }
            )
        return {
            "passed": True,
            "data_mode": "real",
            "source_person": person,
            "graph_space": graph_manifest.space,
            "reader_role": "GUEST",
            "same_company_hops": checks,
            "observation_scope": "single-real-small-neighborhood-sequential",
        }
    finally:
        if client is not None:
            client.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    report = verify(output)
    report_path = args.report or output / "query-validation.json"
    if args.report is None and report_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        report_path = output / f"query-validation-{timestamp}.json"
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
