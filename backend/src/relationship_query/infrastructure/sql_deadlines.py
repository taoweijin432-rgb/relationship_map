"""SQLAlchemy 2.0／PyMySQL请求预算适配；不按请求修改共享池配置。"""

import sqlite3
from collections.abc import Callable
from functools import partial
from math import ceil
from time import monotonic, perf_counter
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import ConnectionPoolEntry, QueuePool
from sqlalchemy.util.queue import Empty, Queue

from relationship_query.domain.path_budget import (
    PathBudget,
    PathBudgetExceeded,
    current_query_budget,
)
from relationship_query.runtime.diagnostics import observe, record_stage, stage
from relationship_query.services.query import QueryError

STATE_KEY = "relationship_query_io_state"


class _DeadlineQueue(Queue[ConnectionPoolEntry]):
    def get(self, block: bool = True, timeout: float | None = None) -> ConnectionPoolEntry:
        budget = current_query_budget()
        if budget is None:
            return super().get(block, timeout)
        budget.check()
        if not block:
            return super().get(False, timeout)
        deadline = monotonic() + timeout if timeout is not None else float("inf")
        with stage("SQL.pool_wait"):
            while True:
                budget.check()
                remaining = min(deadline - monotonic(), budget.deadline - budget.clock())
                try:
                    # 定期响应协作取消；单次池等待仍受原pool_timeout限制。
                    return super().get(True, max(0, min(0.05, remaining)))
                except Empty:
                    budget.check()
                    if monotonic() >= deadline:
                        observe("sql.pool_rejected")
                        raise QueryError("GRAPH_BUSY", "查询连接已满，请稍后重试", 503) from None


class DeadlineQueuePool(QueuePool):
    # QueuePool在2.0系列通过此扩展点创建队列，私有版本适配集中在本文件。
    _queue_class = _DeadlineQueue

    def _do_get(self) -> ConnectionPoolEntry:
        record = super()._do_get()
        try:
            # pre_ping发生在checkout事件之前，复用连接的探活也须限制I/O。
            _prepare_record(record)
            return record
        except BaseException:
            try:
                _checkin(record.dbapi_connection, record)
            finally:
                self._return_conn(record)
            raise


def install_sql_deadlines(
    engine: Engine, *, mysql_connect: Callable[..., Any] | None = None
) -> None:
    if event.contains(engine, "checkout", _checkout):
        return
    event.listen(engine, "checkout", _checkout)
    event.listen(engine, "checkin", _checkin)
    event.listen(engine, "before_cursor_execute", _before_execute, retval=True)
    event.listen(engine, "after_cursor_execute", _after_execute)
    event.listen(engine, "handle_error", _handle_error)
    if engine.dialect.name == "mysql":
        event.listen(engine, "do_connect", partial(_connect_timeout, factory=mysql_connect))


def _connect_timeout(
    dialect: Any,
    record: Any,
    args: Any,
    kwargs: dict,
    *,
    factory: Callable[..., Any] | None = None,
) -> Any:
    budget = current_query_budget()
    # SQLAlchemy重用建连参数字典，不能把某次短预算写回此共享对象。
    configured = dict(kwargs)
    if budget is not None:
        budget.check()
        remaining = budget.deadline - budget.clock()
        for field in ("connect_timeout", "read_timeout", "write_timeout"):
            configured[field] = min(kwargs.get(field) or remaining, remaining)
    with stage("SQL.connect"):
        raw = (factory or dialect.connect)(*args, **configured)
    if budget is not None:
        record.info["relationship_query_initial_io"] = (
            kwargs.get("read_timeout"),
            kwargs.get("write_timeout"),
        )
        try:
            budget.check()
        except PathBudgetExceeded:
            raw.close()
            raise
        raw.connect_timeout = kwargs.get("connect_timeout", getattr(raw, "connect_timeout", 10))
    return raw


def _checkout(raw: Any, record: Any, _proxy: Any) -> None:
    budget = current_query_budget()
    if budget is None:
        return
    budget.check()
    observe("sql.checkout")
    _prepare_record(record)


def _prepare_record(record: Any) -> None:
    budget = current_query_budget()
    raw = record.dbapi_connection
    if budget is None or raw is None:
        return
    budget.check()
    if STATE_KEY in record.info:
        if not isinstance(raw, sqlite3.Connection):
            _mysql_timeout(raw, budget)
        return
    if isinstance(raw, sqlite3.Connection):
        record.info[STATE_KEY] = ("sqlite", raw.execute("PRAGMA busy_timeout").fetchone()[0])
        raw.set_progress_handler(budget.progress, 1000)
        raw.execute(f"PRAGMA busy_timeout={max(1, ceil(_remaining(budget) * 1000))}")
    else:
        initial = record.info.pop("relationship_query_initial_io", None)
        record.info[STATE_KEY] = (
            ("mysql", *initial, initial[0], initial[0])
            if initial
            else (
                "mysql",
                raw._read_timeout,
                raw._write_timeout,
                raw._current_timeout,
                raw._sock.gettimeout(),
            )
        )
        _mysql_timeout(raw, budget)


def _remaining(budget: PathBudget) -> float:
    budget.check()
    return max(0.001, budget.deadline - budget.clock())


def _mysql_timeout(raw: Any, budget: PathBudget) -> None:
    remaining = _remaining(budget)
    raw._read_timeout = min(raw._read_timeout or remaining, remaining)
    raw._write_timeout = min(raw._write_timeout or remaining, remaining)


def _checkin(raw: Any, record: Any) -> None:
    state = record.info.pop(STATE_KEY, None)
    if raw is None or state is None:
        return
    try:
        if state[0] == "sqlite":
            raw.set_progress_handler(None, 0)
            raw.execute(f"PRAGMA busy_timeout={int(state[1])}")
        else:
            raw._read_timeout, raw._write_timeout, raw._current_timeout = state[1:4]
            raw._sock.settimeout(state[4])
    except (sqlite3.Error, OSError, AttributeError) as error:
        record.invalidate(error)
        observe("sql.restore_failed")
        raise QueryError("STORAGE_UNAVAILABLE", "查询连接恢复失败，请稍后重试", 503) from error


def _before_execute(
    connection: Any, _cursor: Any, statement: str, parameters: Any, context: Any, _many: Any
) -> tuple[str, Any]:
    context._relationship_started = perf_counter()
    budget = current_query_budget()
    observe("sql.statement")
    if budget is not None:
        budget.check()
        if connection.dialect.name == "mysql":
            _mysql_timeout(connection.connection.driver_connection, budget)
            if statement.startswith("SELECT ") and "MAX_EXECUTION_TIME(" not in statement[:128]:
                milliseconds = min(3000, ceil(_remaining(budget) * 1000))
                statement = statement.replace(
                    "SELECT ", f"SELECT /*+ MAX_EXECUTION_TIME({milliseconds}) */ ", 1
                )
    return statement, parameters


def _finish_statement(context: Any) -> None:
    started = getattr(context, "_relationship_started", None)
    if started is not None:
        record_stage("SQL.execute", (perf_counter() - started) * 1000)
        del context._relationship_started


def _after_execute(
    _connection: Any, _cursor: Any, _statement: Any, _parameters: Any, context: Any, _many: Any
) -> None:
    _finish_statement(context)


def _handle_error(context: Any) -> None:
    _finish_statement(context.execution_context)
    observe("sql.failure")
    budget = current_query_budget()
    if budget is not None:
        budget.check()
        if budget.interrupted:
            raise PathBudgetExceeded(budget.interrupted)
        if (
            context.dialect.name == "mysql"
            and context.original_exception.args
            and context.original_exception.args[0] == 3024
        ):
            raise PathBudgetExceeded("time_limit")
