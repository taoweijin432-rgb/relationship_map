"""只读诊断实际人物前缀SQL与发布成员过滤；不输出人物字段或搜索原文。"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from relationship_query.benchmark.observe import SQLTrace, Statement, capture_sql, observe_engine
from relationship_query.infrastructure.live_people import (
    PERSON_TABLES,
    LiveRealGraphRepository,
)
from relationship_query.runtime.diagnostics import DiagnosticTrace, capture
from relationship_query.services.query import QueryError

PLAN_FIELDS = {
    "table_name",
    "access_type",
    "possible_keys",
    "key",
    "key_length",
    "used_key_parts",
    "rows_examined_per_scan",
    "rows_produced_per_join",
    "filtered",
    "using_filesort",
    "using_temporary_table",
    "query_cost",
    "read_cost",
    "eval_cost",
    "data_read_per_join",
}


def plan_summary(value: Any) -> Any:
    if isinstance(value, list):
        return [plan_summary(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: plan_summary(item)
        for key, item in value.items()
        if key in PLAN_FIELDS or isinstance(item, (dict, list))
    }


def explain_statement(engine: Engine, statement: Statement) -> dict[str, Any]:
    sql, parameters = statement.sql, statement.parameters
    with engine.connect() as connection:
        planned = connection.exec_driver_sql("EXPLAIN FORMAT=JSON " + sql, parameters).scalar_one()
        actual = connection.exec_driver_sql("EXPLAIN ANALYZE " + sql, parameters).scalar_one()
    return {"estimated": plan_summary(json.loads(planned)), "actual_tree": redact_tree(str(actual))}


def redact_tree(tree: str) -> str:
    lines = []
    for line in tree.splitlines():
        position = re.search(r"\((?:cost|actual time)=", line)
        end = position.start() if position else len(line)
        head = re.sub(r"'(?:\\.|''|[^'])*'", "'<value>'", line[:end])
        head = re.sub(r"\b[0-9]+\b", "<n>", head)
        head = re.sub(r"(?:<n>\s*,\s*)+<n>", "<values>", head)
        if len(head) > 512:
            head = head[:512] + " ... [predicate omitted] "
        lines.append(head + line[end:])
    return "\n".join(lines)


def table_profile(connection: Connection, table: str) -> dict[str, Any]:
    if table not in PERSON_TABLES.values():
        raise ValueError("诊断只接受已绑定的人物来源表")
    columns = list(connection.exec_driver_sql(f"SHOW FULL COLUMNS FROM `{table}`").mappings())
    indexes = list(connection.exec_driver_sql(f"SHOW INDEX FROM `{table}`").mappings())
    return {
        "columns": [
            {key: row[key] for key in ("Field", "Type", "Collation", "Key", "Null")}
            for row in columns
        ],
        "indexes": [
            {
                key: row[key]
                for key in ("Key_name", "Non_unique", "Column_name", "Seq_in_index", "Cardinality")
            }
            for row in indexes
        ],
        "rows": connection.exec_driver_sql(f"SELECT COUNT(*) FROM `{table}`").scalar_one(),
    }


def profile(repository: LiveRealGraphRepository, keywords: list[str], limit: int) -> dict:
    people = repository.people
    if people.engine.dialect.name != "mysql":
        raise ValueError("执行计划诊断需要MySQL8.0.18以上，不能以SQLite计划替代")
    report: dict[str, Any] = {
        "data_version": repository.version,
        "published_sources": sorted(repository.published_sources),
        "tables": {},
        "queries": [],
    }
    with people.engine.connect() as connection:
        report["server"] = dict(
            connection.execute(
                text("SELECT @@version AS version, @@server_uuid AS server_uuid, DATABASE() AS db")
            )
            .mappings()
            .one()
        )
        for source in sorted(repository.published_sources):
            report["tables"][source] = table_profile(connection, people.tables[source].name)
    for keyword in keywords:
        result: dict[str, Any] = {
            "keyword_sha256": hashlib.sha256(keyword.encode()).hexdigest(),
            "keyword_length": len(keyword),
            "limit": limit,
            "plans": {},
        }
        sample = search_sample(repository, keyword, limit)
        result.update(sample.metrics)
        for source in sorted(repository.published_sources):
            name = re.escape(people.tables[source].name)
            selected = [
                row
                for row in sample.statements
                if re.search(rf"\bFROM\s+`?{name}`?(?:\s|$)", row.sql, re.IGNORECASE)
            ]
            unique = {row.sql: row for row in selected}
            try:
                result["plans"][source] = {
                    "captured_queries": len(selected),
                    "queries": [
                        explain_statement(people.engine, row) for row in list(unique.values())[:2]
                    ],
                }
            except (SQLAlchemyError, QueryError, ValueError) as error:
                # 受源库max_execution_time限制，失败也写入报告，不能当作零行或跳过。
                result["plans"][source] = {"error": type(error).__name__}
        report["queries"].append(result)
    return report


@dataclass
class CapturedSearch:
    metrics: dict[str, Any]
    statements: list[Statement] = field(repr=False)


def search_sample(repository: LiveRealGraphRepository, keyword: str, limit: int) -> CapturedSearch:
    trace = DiagnosticTrace()
    sql = SQLTrace(owns_progress=False)
    candidate_rows: list[int] = []

    def read_rows(_connection: Any, cursor: Any, sql: str, *_args: Any) -> None:
        if sql.lstrip().upper().startswith("SELECT"):
            candidate_rows.append(cursor.rowcount)

    event.listen(repository.people.engine, "after_cursor_execute", read_rows)
    started = perf_counter()
    result: dict[str, Any] = {}
    try:
        with capture(trace), observe_engine(repository.people.engine), capture_sql(sql):
            repository.verify_snapshot()
            items = repository.suggest_people(keyword, limit)
            repository.verify_snapshot()
        result.update(passed=True, items=len(items))
    except QueryError as error:
        result.update(passed=False, code=error.code)
    finally:
        event.remove(repository.people.engine, "after_cursor_execute", read_rows)
    result.update(
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
        # 同一诊断也可独立在48a1adb部署版运行，该版只有阶段计时。
        observations=getattr(trace, "observations", {}),
        stages=trace.totals(),
        source_queries=len(candidate_rows),
        candidate_rows=sum(candidate_rows),
    )
    return CapturedSearch(result, sql.statements)
