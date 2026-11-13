import hashlib
import math
import os
import platform
import sqlite3
import sys
from pathlib import Path
from typing import Any

from relationship_query.infrastructure.sqlite import open_engine


def file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment() -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return {
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "sqlite": sqlite3.sqlite_version,
        "backend_source_sha256": digest.hexdigest(),
    }


def _distribution(values: list[int]) -> dict[str, int]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0, "p95": 0, "p99": 0, "max": 0}
    return {
        **{
            name: ordered[math.ceil(len(ordered) * q) - 1]
            for name, q in [("p50", 0.5), ("p95", 0.95), ("p99", 0.99)]
        },
        "max": ordered[-1],
    }


def distribution(path: Path) -> dict[str, object]:
    engine = open_engine(path)
    try:
        with engine.connect() as connection:

            def scalar(sql: str) -> int:
                return int(connection.exec_driver_sql(sql).scalar() or 0)

            person_counts = [
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT count(f.id) FROM demo_person p LEFT JOIN demo_fact f "
                    "ON f.person_id=p.id AND f.active=1 WHERE p.active=1 GROUP BY p.id"
                )
            ]
            degrees = {
                kind: _distribution(
                    [
                        row[0]
                        for row in connection.exec_driver_sql(
                            "SELECT count(DISTINCT f.person_id) FROM demo_fact f "
                            "JOIN demo_person p ON p.id=f.person_id "
                            "WHERE p.active=1 AND f.active=1 AND f.type=? GROUP BY f.entity_id",
                            (kind,),
                        )
                    ]
                )
                for kind in ("employment", "education")
            }
            return {
                "active_people": scalar("SELECT count(*) FROM demo_person WHERE active=1"),
                "active_facts_on_active_people": scalar(
                    "SELECT count(*) FROM demo_fact f JOIN demo_person p ON p.id=f.person_id "
                    "WHERE p.active=1 AND f.active=1"
                ),
                "unknown_employment_dates": scalar(
                    "SELECT count(*) FROM demo_fact WHERE type='employment' AND active=1 "
                    "AND (start_month IS NULL OR (end_month IS NULL AND is_current=0))"
                ),
                "per_person_active_facts": _distribution(person_counts),
                "active_entity_people": degrees,
                "sqlite_pragmas": {
                    key: connection.exec_driver_sql(f"PRAGMA {key}").scalar()
                    for key in ("page_size", "cache_size", "journal_mode")
                },
                "indexes": [
                    dict(row._mapping)
                    for row in connection.exec_driver_sql(
                        "SELECT name, sql FROM sqlite_master WHERE type='index' ORDER BY name"
                    )
                ],
            }
    finally:
        engine.dispose()


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# R01 模拟规模与查询诊断报告",
        "",
        f"实验标签：{report['label']}；生成于 {report['created_at']}。",
        "",
        "仅固定种子虚构数据、单进程顺序请求；ASGI TestClient 包含路由及序列化，"
        "不含网络、网关或并发。不能推算百万级生产容量。",
        "",
        "每个场景在独立进程中首次观测一次，再记录预热重复；"
        "首次观测不是清空操作系统缓存的冷启动。P95 为最近秩法，小样本只供观察。",
        "",
        "阶段耗时为嵌套的 inclusive wall time，不能相加。"
        "cursor_execute_ms 不包含后续全部 fetch；VM 步数是近似值，不是扫描行数。"
        "路径保留自己的执行预算，不被诊断器覆盖。",
        "",
        f"环境：`{report['environment']}`",
        "",
        "| 人物规模 | 场景 | 策略 | 首次 ms | 预热 P50 / P95 ms | "
        "响应 KiB | 路径数 | 受限原因 / 错误 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for dataset in report["datasets"]:
        for result in dataset["cases"]:
            if not result.get("ok"):
                lines.append(
                    f"| {dataset['size']} | {result['name']} | {result['strategy']} "
                    f"| — | — | — | — | {result.get('error')} |"
                )
                continue
            data = result["result"]
            first = data["samples"][0]
            summary = data["summary"]
            reason = ", ".join(summary["truncation_reasons"]) or (
                "HTTP 错误" if summary["errors"] else "无"
            )
            lines.append(
                f"| {dataset['size']} | {result['name']} | {result['strategy']} "
                f"| {first['http_ms']} | {summary['p50_ms']} / {summary['p95_ms']} "
                f"| {first['response_bytes'] / 1024:.1f} "
                f"| {first['result']['path_count']} | {reason} |"
            )
    lines.extend(["", "## 数据与完整性", ""])
    for dataset in report["datasets"]:
        lines.extend(
            [
                f"- {dataset['size']} 人：`{dataset['generation']}`",
                f"- 分布：`{dataset['distribution']}`",
                f"- 数据库查询前后摘要相同：{dataset.get('database_unchanged')}",
            ]
        )
    lines.extend(
        [
            "",
            f"默认演示库保持不变：{report.get('default_database_unchanged')}",
            "",
            "每次请求的阶段、SQL 模板、参数、EXPLAIN QUERY PLAN、样本和结果数量"
            "均保存在 report.json；"
            "错误与外部观察预算会明确记录，不算作正常空结果。",
            "",
        ]
    )
    return "\n".join(lines)
