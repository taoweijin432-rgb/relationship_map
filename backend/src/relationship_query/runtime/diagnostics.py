import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


def configure_logging() -> None:
    level = os.environ.get("RELATIONSHIP_QUERY_LOG_LEVEL", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("无效的RELATIONSHIP_QUERY_LOG_LEVEL")
    logger = logging.getLogger("relationship_query")
    logger.setLevel(level)
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)


@dataclass
class Stage:
    name: str
    elapsed_ms: float


@dataclass
class DiagnosticTrace:
    stages: list[Stage] = field(default_factory=list)
    request_id: str = "-"
    observations: dict[str, int] = field(default_factory=dict)
    jobs: list[tuple[str, str, str]] = field(default_factory=list)
    terminal_reason: str | None = None
    job_id: str = "-"

    def totals(self) -> dict[str, dict[str, float | int]]:
        result: dict[str, dict[str, float | int]] = {}
        for stage in self.stages:
            row = result.setdefault(stage.name, {"calls": 0, "inclusive_ms": 0.0})
            row["calls"] += 1
            row["inclusive_ms"] += stage.elapsed_ms
        return {
            key: {"calls": int(row["calls"]), "inclusive_ms": round(row["inclusive_ms"], 3)}
            for key, row in result.items()
        }


_current: ContextVar[DiagnosticTrace | None] = ContextVar("query_diagnostic_trace", default=None)


def request_id() -> str:
    trace = _current.get()
    return trace.request_id if trace else "-"


def job_id() -> str:
    trace = _current.get()
    return trace.job_id if trace else "-"


def terminate(reason: str) -> None:
    """首次终止决定唯一归因；后续错误格式化不覆盖原始拒绝点。"""
    trace = _current.get()
    if trace is not None and trace.terminal_reason is None:
        trace.terminal_reason = reason


def error_reason(code: str) -> str:
    if code in {"GRAPH_QUERY_LIMIT", "PERSON_QUERY_LIMIT"}:
        return "budget"
    if code.endswith("INTEGRITY") or code.endswith("VERSION_MISMATCH"):
        return "integrity"
    if code.endswith("UNAVAILABLE"):
        return "dependency"
    return "application_error"


def observe(name: str, count: int = 1) -> None:
    """只接受内部固定指标名；不记录查询参数或人物数据。"""
    trace = _current.get()
    if trace is not None:
        trace.observations[name] = trace.observations.get(name, 0) + count


def link_job(identity: str, cost: str, role: str) -> None:
    trace = _current.get()
    if trace is not None:
        trace.jobs.append((identity, cost, role))


def record_stage(name: str, elapsed_ms: float) -> None:
    trace = _current.get()
    if trace is not None:
        trace.stages.append(Stage(name, elapsed_ms))


@contextmanager
def stage(name: str) -> Iterator[None]:
    trace = _current.get()
    started = perf_counter()
    try:
        yield
    finally:
        if trace is not None:
            trace.stages.append(Stage(name, (perf_counter() - started) * 1000))


@contextmanager
def capture(trace: DiagnosticTrace, *, include_in_parent: bool = False) -> Iterator[None]:
    parent = _current.get()
    token = _current.set(trace)
    try:
        yield
    finally:
        _current.reset(token)
        # HTTP自带观测不能遮住外层基准工具的采样；同一trace嵌套时不重复累计。
        if include_in_parent and parent is not None and parent is not trace:
            parent.stages.extend(trace.stages)
            parent.jobs.extend(trace.jobs)
            for name, count in trace.observations.items():
                parent.observations[name] = parent.observations.get(name, 0) + count


def traced(name: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            with stage(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate
