"""同一 MySQL 模拟快照的 SQL／图内路径对照；可选旧候选辅助，非生产负载测试。"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from relationship_query.benchmark.cases import Case, cases
from relationship_query.benchmark.report import environment, file_digest
from relationship_query.benchmark.run import compare_strategies, isolated_case
from relationship_query.infrastructure.graph_model import read_manifest
from relationship_query.infrastructure.mysql import open_mysql_engine
from relationship_query.infrastructure.snapshots import snapshot_digest
from relationship_query.settings import DEFAULT_DATABASE


def returned_paths_equal(results: list[dict[str, Any]]) -> bool:
    grouped = {(r["name"], r["strategy"]): r for r in results if r.get("ok")}
    for (name, strategy), graph in grouped.items():
        if strategy != "nebula" or (name, "sql") not in grouped:
            continue
        sql_samples = grouped[(name, "sql")]["result"]["samples"]
        graph_samples = graph["result"]["samples"]
        if len(sql_samples) != len(graph_samples) or any(
            a["path_signatures"] != b["path_signatures"]
            for a, b in zip(sql_samples, graph_samples)
        ):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--include-candidates", action="store_true")
    args = parser.parse_args()
    value = os.environ.get("RELATIONSHIP_MYSQL_URL")
    if not value or args.output.exists() or not 1 <= args.repeats <= 30:
        parser.error("需要独立 MySQL 实验连接、新报告目录和 1–30 次预热重复")
    manifest = read_manifest(args.manifest)
    engine = open_mysql_engine(value)
    with engine.connect() as connection:
        before_sql = snapshot_digest(connection)
    if before_sql != manifest.source_digest:
        parser.error("SQL 与图快照内容不一致")
    selected = [case for case in cases(10000) if case.name.startswith("path_")]
    base = {
        "reference_id": "p:000004",
        "candidate_id": "p:000005",
        "scope": {"relation_type": "same_company_overlap"},
    }
    extra = {
        "path_source": {**base, "intermediate_source": "expert"},
        "path_window": {
            **base,
            "scope": {
                "relation_type": "same_company_overlap",
                "relation_start_month": 202012,
                "relation_end_month": 202101,
                "min_overlap_months": 2,
            },
        },
        "path_school": {**base, "scope": {"relation_type": "same_school"}},
        "path_unknown": {**base, "reference_id": "p:000009"},
        "path_candidate_one": {**base, "limits": {"candidate_limit": 1}},
    }
    selected.extend(
        Case(name, "POST", "/api/v1/relations/paths", body)
        for name, body in extra.items()
    )
    args.output.mkdir(parents=True, exist_ok=False)
    before_file, before_demo = file_digest(args.input), file_digest(DEFAULT_DATABASE)
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "environment": environment(),
        "data_mode": "mock",
        "data_version": manifest.data_version,
        "source_digest": manifest.source_digest,
        "projection": manifest.model_dump(),
        "method": "sequential ASGI API; real local MySQL TCP and Nebula RPC; no HTTP concurrency",
        "repeats": args.repeats,
        "case_wall_timeout_s": 30,
        "stop_on_graph_error_or_time_limit": True,
        "stopped_early": False,
        "cases": [],
    }
    try:
        for case in selected:
            modes = [("sql", None, "paths"), ("nebula", args.manifest, "paths")]
            if args.include_candidates:
                modes.append(("nebula_sql", args.manifest, "candidates"))
            for name, graph, graph_engine in modes:
                print(f"{case.name} / {name}", file=sys.stderr, flush=True)
                os.environ["RELATIONSHIP_GRAPH_ENGINE"] = graph_engine
                result = isolated_case(
                    args.input,
                    case,
                    "current",
                    args.repeats,
                    2000,
                    mysql_url=value,
                    graph_manifest=graph,
                )
                report["cases"].append({"name": case.name, "strategy": name, **result})
                (args.output / "report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2)
                )
                if graph and (
                    not result.get("ok")
                    or result["result"]["summary"]["errors"]
                    or result["result"]["summary"]["truncation_reasons"].get("time_limit")
                ):
                    report["stopped_early"] = True
                    report["stop_case"] = case.name + ":" + name
                    break
            if report["stopped_early"]:
                break
        adapted = [
            {**item, "strategy": "baseline" if item["strategy"] == "sql" else "current"}
            for item in report["cases"]
            if item["strategy"] in {"sql", "nebula"}
        ]
        report["comparisons"] = compare_strategies(adapted)
        report["errors"] = [
            item["name"] + ":" + item["strategy"]
            for item in report["cases"]
            if not item.get("ok") or item["result"]["summary"]["errors"]
        ]
        report["mismatches"] = [
            item["name"]
            for item in report["comparisons"]
            if item["complete_response_equal"] is False
            or not item["common_returned_paths_equal"]
        ]
        report["returned_paths_equal"] = returned_paths_equal(report["cases"])
        report["backend_markers_correct"] = all(
            sample["result"]["query_backend"] == item["strategy"]
            for item in report["cases"]
            if item.get("ok")
            for sample in item["result"]["samples"]
            if sample["status_code"] == 200
        )
        with engine.connect() as connection:
            report["sql_unchanged"] = snapshot_digest(connection) == before_sql
        report["input_unchanged"] = file_digest(args.input) == before_file
        report["default_unchanged"] = file_digest(DEFAULT_DATABASE) == before_demo
        report["completed"] = not report["stopped_early"]
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
    finally:
        engine.dispose()
    keys = (
        "errors",
        "mismatches",
        "backend_markers_correct",
        "sql_unchanged",
        "input_unchanged",
        "default_unchanged",
        "returned_paths_equal",
        "completed",
    )
    print(json.dumps({key: report[key] for key in keys}))
    return (
        0
        if not report["errors"]
        and not report["mismatches"]
        and all(report[k] for k in keys[2:])
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
