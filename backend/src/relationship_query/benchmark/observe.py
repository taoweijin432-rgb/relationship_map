import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine


@dataclass
class Statement:
    sql: str
    parameters: Any
    started: float
    elapsed_ms: float = 0
    failed: bool = False


@dataclass
class SQLTrace:
    timeout_ms: int = 2000
    owns_progress: bool = True
    statements: list[Statement] = field(default_factory=list)
    pending: dict[int, Statement] = field(default_factory=dict)
    vm_steps_estimate: int = 0
    interrupted: str | None = None
    started: float = field(default_factory=perf_counter)

    def progress(self) -> int:
        self.vm_steps_estimate += 1000
        if (perf_counter() - self.started) * 1000 >= self.timeout_ms:
            self.interrupted = "benchmark_sql_time_limit"
        elif self.vm_steps_estimate >= 20_000_000:
            self.interrupted = "benchmark_sql_step_limit"
        return int(self.interrupted is not None)

    def finish(self, context: object, failed: bool = False) -> None:
        row = self.pending.pop(id(context), None)
        if row is not None:
            row.elapsed_ms = (perf_counter() - row.started) * 1000
            row.failed = failed


_sql_trace: ContextVar[SQLTrace | None] = ContextVar("benchmark_sql_trace", default=None)


@contextmanager
def capture_sql(trace: SQLTrace) -> Iterator[None]:
    token = _sql_trace.set(trace)
    try:
        yield
    finally:
        _sql_trace.reset(token)


@contextmanager
def observe_engine(engine: Engine) -> Iterator[None]:
    def checkout(dbapi: sqlite3.Connection, _record: Any, _proxy: Any) -> None:
        trace = _sql_trace.get()
        if engine.dialect.name == "sqlite" and trace is not None and trace.owns_progress:
            dbapi.set_progress_handler(trace.progress, 1000)

    def checkin(dbapi: sqlite3.Connection | None, _record: Any) -> None:
        if engine.dialect.name == "sqlite" and dbapi is not None:
            dbapi.set_progress_handler(None, 0)

    def before(
        _conn: Any, _cursor: Any, sql: str, parameters: Any, context: Any, _many: bool
    ) -> None:
        trace = _sql_trace.get()
        if trace is not None:
            row = Statement(sql, parameters, perf_counter())
            trace.statements.append(row)
            trace.pending[id(context)] = row

    def after(_conn: Any, _cursor: Any, _sql: str, _params: Any, context: Any, _many: bool) -> None:
        trace = _sql_trace.get()
        if trace is not None:
            trace.finish(context)

    def failed(context: Any) -> None:
        trace = _sql_trace.get()
        if trace is not None:
            trace.finish(context.execution_context, True)

    listeners: list[tuple[str, Callable[..., Any]]] = [
        ("checkout", checkout),
        ("checkin", checkin),
        ("before_cursor_execute", before),
        ("after_cursor_execute", after),
        ("handle_error", failed),
    ]
    for name, callback in listeners:
        event.listen(engine, name, callback)
    try:
        yield
    finally:
        for name, callback in listeners:
            event.remove(engine, name, callback)


def explain(engine: Engine, statements: list[Statement]) -> list[dict[str, object]]:
    result = []
    seen = set()
    with engine.connect() as connection:
        for row in statements:
            if not row.sql.lstrip().upper().startswith("SELECT") or row.sql in seen:
                continue
            seen.add(row.sql)
            prefix = (
                "EXPLAIN FORMAT=JSON " if engine.dialect.name == "mysql" else "EXPLAIN QUERY PLAN "
            )
            plan = connection.exec_driver_sql(prefix + row.sql, row.parameters).all()
            result.append(
                {
                    "sql": row.sql,
                    "parameters": row.parameters,
                    "plan": [list(entry) for entry in plan],
                    "execution_failed": row.failed,
                }
            )
    return result
