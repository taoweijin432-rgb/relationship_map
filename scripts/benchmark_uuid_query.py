"""顺序 ASGI 查询观察，记录 SQL／图调用数并对照冻结响应，输出必须为新目录。"""

import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from fastapi.testclient import TestClient
from relationship_query.app import create_app
from relationship_query.infrastructure.source_releases import read_bundle
from relationship_query.infrastructure.uuid_verification import verify_bundle_graph
from sqlalchemy import event


def comparable(value):
    if isinstance(value, dict):
        return {
            key: comparable(item) for key, item in value.items() if key != "next_cursor"
        }
    if isinstance(value, list):
        return [comparable(item) for item in value]
    return value


def run(directory: Path, output: Path, baseline: Path | None) -> dict:
    if output.exists():
        raise FileExistsError("耗时观察使用新目录，保留历史记录")
    verify_bundle_graph(directory)
    bundle = read_bundle(directory)
    star = json.loads((directory / "report.json").read_text()).get("candidate_count")
    cases = [
        ("all", "/api/v1/persons/p:expert:1/relations/search", dict(page_size=20)),
        (
            "major",
            "/api/v1/persons/p:expert:1/relations/search",
            dict(page_size=20, relation_type="same_major"),
        ),
        (
            "compare",
            "/api/v1/persons/compare",
            dict(reference_id="p:expert:1", candidate_id="p:resume:2"),
        ),
    ]
    if star:
        cases[1] = (
            "sparse",
            cases[0][1],
            dict(page_size=50, position_titles=["入选职位"]),
        )
    output.mkdir(parents=True, exist_ok=False)
    results = []
    with TestClient(
        create_app(
            source_manifest=directory / "manifest.json",
            source_mysql_url=bundle.mysql_url,
        )
    ) as client:
        repository = client.app.state.query_service.repository
        graph = client.app.state.query_service.graph.client
        counters = {"sql": 0, "graph": 0}

        def sql_count(*args):
            counters["sql"] += 1

        original = graph.execute

        def graph_count(*args, **kwargs):
            counters["graph"] += 1
            return original(*args, **kwargs)

        event.listen(repository.engine, "before_cursor_execute", sql_count)
        graph.execute = graph_count
        try:
            for name, url, body in cases:
                samples = []
                for index in range(7):
                    counters.update(sql=0, graph=0)
                    start = perf_counter()
                    response = client.post(url, json=body)
                    elapsed = round((perf_counter() - start) * 1000, 3)
                    if response.status_code != 200:
                        raise RuntimeError(f"场景 {name} 返回 {response.status_code}")
                    samples.append(dict(elapsed_ms=elapsed, **counters))
                    if index == 0:
                        payload = response.json()
                        (output / f"{name}-response.json").write_text(response.text)
                        if baseline:
                            frozen = json.loads(
                                (baseline / f"{name}-response.json").read_text()
                            )
                            if comparable(payload) != comparable(frozen):
                                raise AssertionError(f"场景 {name} 与冻结响应不一致")
                results.append(
                    dict(
                        case=name,
                        request=body,
                        url=url,
                        samples=samples,
                        median_ms=round(median(s["elapsed_ms"] for s in samples), 3),
                    )
                )
        finally:
            graph.execute = original
            event.remove(repository.engine, "before_cursor_execute", sql_count)
    report = dict(
        data_mode="mock",
        data_version=bundle.manifest.data_version,
        sample_kind="star" if star else "same-63-person-source",
        candidate_count=star,
        execution="sequential ASGI, seven samples per case",
        startup_included=False,
        baseline_comparison=bool(baseline),
        cases=results,
    )
    (output / "measurements.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    report = run(args.input, args.output, args.baseline)
    print(
        json.dumps(
            [
                {k: v for k, v in row.items() if k in ("case", "median_ms")}
                | {
                    "sql_calls": row["samples"][-1]["sql"],
                    "graph_calls": row["samples"][-1]["graph"],
                }
                for row in report["cases"]
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
