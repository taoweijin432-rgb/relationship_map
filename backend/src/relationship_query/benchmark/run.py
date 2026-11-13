import argparse
import json
import multiprocessing
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from relationship_query.benchmark.cases import Case, cases
from relationship_query.benchmark.dataset import create_database
from relationship_query.benchmark.measure import worker
from relationship_query.benchmark.report import distribution, environment, file_digest, markdown
from relationship_query.settings import DEFAULT_DATABASE


def isolated_case(
    database: Path,
    case: Case,
    strategy: str,
    repeats: int,
    sql_timeout_ms: int,
    timeout: float = 30,
    *,
    mysql_url: str | None = None,
    graph_manifest: Path | None = None,
) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=worker,
        args=(
            send,
            str(database),
            case,
            repeats,
            sql_timeout_ms,
            strategy,
            mysql_url,
            str(graph_manifest) if graph_manifest else None,
        ),
    )
    process.start()
    send.close()
    timed_out = False
    try:
        if not receive.poll(timeout):
            timed_out = True
            return {"ok": False, "error": "harness_case_wall_timeout"}
        try:
            return receive.recv()
        except EOFError:
            return {"ok": False, "error": f"worker_exited_without_result:{process.exitcode}"}
    finally:
        if timed_out and process.is_alive():
            process.terminate()
        process.join(2)
        if process.is_alive():
            process.terminate()
            process.join(2)
        if process.is_alive():
            process.kill()
            process.join()
        receive.close()


def _write(output: Path, report: dict[str, Any]) -> None:
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "report.md").write_text(markdown(report), encoding="utf-8")


def compare_strategies(results: list[dict[str, Any]]) -> list[dict[str, object]]:
    grouped = {(item["name"], item["strategy"]): item for item in results if item.get("ok")}
    comparisons = []
    for name, strategy in grouped:
        if strategy != "current" or (name, "baseline") not in grouped:
            continue
        before = grouped[(name, "baseline")]["result"]["samples"][0]
        after = grouped[(name, "current")]["result"]["samples"][0]
        both_success = before["status_code"] == after["status_code"] == 200
        complete = (
            both_success
            and before["result"]["search_complete"] is not False
            and after["result"]["search_complete"] is not False
        )
        common = before["path_signatures"].keys() & after["path_signatures"].keys()
        comparisons.append(
            {
                "name": name,
                "both_success": both_success,
                "both_searches_complete": complete,
                "complete_response_equal": before["semantic_sha256"] == after["semantic_sha256"]
                if complete
                else None,
                "common_returned_paths_equal": all(
                    before["path_signatures"][key] == after["path_signatures"][key]
                    for key in common
                ),
                "common_path_count": len(common),
            }
        )
    return comparisons


def run(
    output: Path,
    sizes: list[int],
    repeats: int = 7,
    seed: int = 42,
    strategies: list[str] | None = None,
    keep_databases: bool = False,
    selected: list[str] | None = None,
    label: str = "r01",
    sql_timeout_ms: int = 2000,
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"请使用新的报告目录，不覆盖已有结果：{output}")
    if not sizes or any(size < 2000 or size > 100000 for size in sizes) or not 1 <= repeats <= 30:
        raise ValueError("规模范围 2000–100000；预热重复范围 1–30")
    if seed < 0 or not 10 <= sql_timeout_ms <= 10000:
        raise ValueError("种子必须非负，观察 SQL 时间预算范围 10–10000 毫秒")
    strategies = strategies or ["baseline", "current"]
    if not strategies or any(strategy not in {"baseline", "current"} for strategy in strategies):
        raise ValueError("未知执行策略")
    known = {case.name for case in cases(sizes[0])}
    if selected and not set(selected) <= known:
        raise ValueError("未知场景名称")
    output.mkdir(parents=True)
    before_demo = file_digest(DEFAULT_DATABASE)
    report: dict[str, Any] = {
        "report_version": "1",
        "data_mode": "mock",
        "label": label,
        "created_at": datetime.now(UTC).isoformat(),
        "environment": environment(),
        "config": {
            "sizes": sizes,
            "repeats": repeats,
            "seed": seed,
            "strategies": strategies,
            "sql_timeout_ms": sql_timeout_ms,
            "case_wall_timeout_s": 30,
            "keep_databases": keep_databases,
        },
        "datasets": [],
    }
    for size in sizes:
        with tempfile.TemporaryDirectory(prefix="relationship-scale-") as temporary:
            database = (output if keep_databases else Path(temporary)) / f"scale-{size}.sqlite"
            generation = create_database(
                database,
                size,
                seed,
                progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
            info: dict[str, Any] = {
                "size": size,
                "database": str(database) if keep_databases else None,
                "generation": generation,
                "distribution": distribution(database),
                "cases": [],
            }
            report["datasets"].append(info)
            original = file_digest(database)
            for case in cases(size):
                if selected and case.name not in selected:
                    continue
                for strategy in strategies:
                    print(f"{size} 人 / {case.name} / {strategy}", file=sys.stderr, flush=True)
                    result = isolated_case(database, case, strategy, repeats, sql_timeout_ms)
                    info["cases"].append({"name": case.name, "strategy": strategy, **result})
                    _write(output, report)
            info["database_unchanged"] = original == file_digest(database)
            info["strategy_comparisons"] = compare_strategies(info["cases"])
    report["default_database_unchanged"] = before_demo == file_digest(DEFAULT_DATABASE)
    report["completed"] = True
    report["execution_errors"] = [
        f"{dataset['size']}:{case['name']}:{case['strategy']}"
        for dataset in report["datasets"]
        for case in dataset["cases"]
        if not case.get("ok")
    ]
    _write(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="隔离的虚构数据规模诊断，不是生产容量测试")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=int, nargs="+", default=[10000, 100000])
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--strategy", choices=["both", "baseline", "current"], default="both")
    parser.add_argument("--keep-databases", action="store_true")
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--label", default="r01")
    parser.add_argument("--sql-timeout-ms", type=int, default=2000)
    args = parser.parse_args()
    try:
        result = run(
            args.output.resolve(),
            args.sizes,
            args.repeats,
            args.seed,
            ["baseline", "current"] if args.strategy == "both" else [args.strategy],
            args.keep_databases,
            args.cases,
            args.label,
            args.sql_timeout_ms,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"报告：{args.output.resolve() / 'report.md'}")
    safe = result["default_database_unchanged"] and all(
        item["database_unchanged"] for item in result["datasets"]
    )
    consistent = all(
        comparison["complete_response_equal"] is not False
        and comparison["common_returned_paths_equal"]
        for dataset in result["datasets"]
        for comparison in dataset["strategy_comparisons"]
    )
    return 0 if safe and consistent and not result["execution_errors"] else 1
