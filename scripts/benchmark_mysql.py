"""比较同一虚构快照的 SQLite／本机 MySQL；ASGI 顺序观察，不是生产压测。"""

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from relationship_query.benchmark.cases import cases
from relationship_query.benchmark.report import environment, file_digest
from relationship_query.benchmark.run import compare_strategies, isolated_case
from relationship_query.infrastructure.mysql import open_mysql_engine
from relationship_query.infrastructure.read_model import schema
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.settings import DEFAULT_DATABASE
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


def database_digest(engine: Engine) -> str:
    digest = hashlib.sha256()
    with engine.connect() as connection:
        for table in schema.sorted_tables:
            digest.update(table.name.encode())
            for row in connection.execute(
                select(table).order_by(*table.primary_key.columns)
            ):
                digest.update(
                    json.dumps(list(row), sort_keys=True, ensure_ascii=False).encode()
                )
    return digest.hexdigest()


def analyze(engine: Engine, result: dict[str, Any]) -> None:
    if not result.get("ok"):
        return
    for query in result["result"]["query_plans"]:
        try:
            with engine.connect() as connection:
                query["analyze"] = [
                    list(row)
                    for row in connection.exec_driver_sql(
                        "EXPLAIN ANALYZE " + query["sql"], query["parameters"]
                    )
                ]
        except SQLAlchemyError as exc:
            # 实验边界保留显式执行失败；不把计划失败当作已验证。
            query["analyze_error"] = type(exc).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, choices=[10000, 100000], required=True)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--analyze", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or not args.input.is_file() or not 1 <= args.repeats <= 30:
        parser.error("输入必须存在、输出必须是新目录、重复次数 1–30")
    value = os.environ.get("RELATIONSHIP_MYSQL_URL")
    if not value:
        parser.error("请先加载实验目录 .env 的 RELATIONSHIP_MYSQL_URL")
    engine = open_mysql_engine(value)
    query = SQLRepository(engine)
    if query.version != f"scale-v1-{args.size}-42":
        parser.error("规模／版本与数据库不符，此入口只测种子 42 的 R01 数据")
    args.output.mkdir(parents=True, exist_ok=False)
    original, default_before = file_digest(args.input), file_digest(DEFAULT_DATABASE)
    mysql_before = database_digest(engine)
    with engine.connect() as connection:
        server = dict(
            connection.execute(
                text(
                    "SELECT VERSION() AS version, @@innodb_buffer_pool_size AS buffer_pool_bytes, "
                    "@@max_connections AS max_connections, @@collation_server AS server_collation"
                )
            )
            .mappings()
            .one()
        )
    report: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "data_mode": "mock",
        "method": "ASGI sequential; native local MySQL TCP; no HTTP socket or concurrency",
        "environment": environment(),
        "mysql": server,
        "database": engine.url.database,
        "size": args.size,
        "data_version": query.version,
        "reference_month": query.reference_month,
        "snapshot_sha256": original,
        "warm_repeats": args.repeats,
        "sql_timeout_ms": 3000,
        "case_wall_timeout_s": 30,
        "cases": [],
    }
    try:
        for case in cases(args.size):
            for label, url in (("sqlite", None), ("mysql", value)):
                print(
                    f"{args.size} / {case.name} / {label}", file=sys.stderr, flush=True
                )
                result = isolated_case(
                    args.input, case, "current", args.repeats, 2000, mysql_url=url
                )
                if label == "mysql" and args.analyze:
                    analyze(engine, result)
                report["cases"].append({"name": case.name, "strategy": label, **result})
                (args.output / "report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2)
                )
        adapted = [
            {
                **item,
                "strategy": "baseline" if item["strategy"] == "sqlite" else "current",
            }
            for item in report["cases"]
        ]
        report["comparisons"] = compare_strategies(adapted)
        report["snapshot_unchanged"] = original == file_digest(args.input)
        report["default_database_unchanged"] = default_before == file_digest(
            DEFAULT_DATABASE
        )
        report["mysql_unchanged"] = mysql_before == database_digest(engine)
        report["mysql_logical_sha256"] = mysql_before
        report["errors"] = [
            f"{item['name']}:{item['strategy']}"
            for item in report["cases"]
            if not item.get("ok") or item["result"]["summary"]["errors"]
        ]
        report["semantic_mismatches"] = [
            item["name"]
            for item in report["comparisons"]
            if item["complete_response_equal"] is False
            or not item["common_returned_paths_equal"]
        ]
        report["completed"] = True
        report["plan_errors"] = [
            f"{item['name']}:{index}"
            for item in report["cases"]
            if item.get("ok")
            for index, plan in enumerate(item["result"]["query_plans"])
            if plan.get("analyze_error")
        ]
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
    finally:
        engine.dispose()
    passed = (
        not report["errors"]
        and not report["plan_errors"]
        and not report["semantic_mismatches"]
        and all(
            report[key]
            for key in (
                "snapshot_unchanged",
                "default_database_unchanged",
                "mysql_unchanged",
            )
        )
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "errors",
                    "semantic_mismatches",
                    "snapshot_unchanged",
                    "default_database_unchanged",
                    "mysql_unchanged",
                )
            }
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
