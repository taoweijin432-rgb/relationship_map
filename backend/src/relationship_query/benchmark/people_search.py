"""只读诊断实际人物前缀SQL与发布成员过滤；不输出人物字段或搜索原文。"""

import hashlib
import json
import re
from time import perf_counter
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from relationship_query.benchmark.observe import SQLTrace, capture_sql, observe_engine
from relationship_query.domain.models import Source
from relationship_query.infrastructure.live_people import (
    PERSON_TABLES,
    LiveRealGraphRepository,
    MySQLPeople,
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


def explain(people: MySQLPeople, source: Source, keyword: str) -> dict[str, Any]:
    trace = SQLTrace(owns_progress=False)
    with observe_engine(people.engine), capture_sql(trace):
        people.suggestions(source, keyword, None)
    statements = [row for row in trace.statements if row.sql.lstrip().upper().startswith("SELECT")]
    if len(statements) != 1:
        raise ValueError("人物来源实际查询应只有一条SELECT，不能用自拟SQL替代")
    sql, parameters = statements[0].sql, statements[0].parameters
    with people.engine.connect() as connection:
        planned = connection.exec_driver_sql("EXPLAIN FORMAT=JSON " + sql, parameters).scalar_one()
        actual = connection.exec_driver_sql("EXPLAIN ANALYZE " + sql, parameters).scalar_one()
    # TREE仍保留算子、actual rows／loops和计时；删除所有引号内绑定值。
    actual = re.sub(r"'(?:\\.|''|[^'])*'", "'<value>'", str(actual))
    return {"estimated": plan_summary(json.loads(planned)), "actual_tree": actual}


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
        for source in sorted(repository.published_sources):
            try:
                result["plans"][source] = explain(people, source, keyword)
            except (SQLAlchemyError, QueryError, ValueError) as error:
                # 受源库max_execution_time限制，失败也写入报告，不能当作零行或跳过。
                result["plans"][source] = {"error": type(error).__name__}
        result.update(search_sample(repository, keyword, limit))
        report["queries"].append(result)
    return report


def search_sample(repository: LiveRealGraphRepository, keyword: str, limit: int) -> dict[str, Any]:
    trace = DiagnosticTrace()
    candidate_rows: list[int] = []

    def read_rows(_connection: Any, cursor: Any, sql: str, *_args: Any) -> None:
        if sql.lstrip().upper().startswith("SELECT"):
            candidate_rows.append(cursor.rowcount)

    event.listen(repository.people.engine, "after_cursor_execute", read_rows)
    started = perf_counter()
    result: dict[str, Any] = {}
    try:
        with capture(trace):
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
    return result
