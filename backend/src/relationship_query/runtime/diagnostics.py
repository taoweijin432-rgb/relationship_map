from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from time import perf_counter
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


@dataclass
class Stage:
    name: str
    elapsed_ms: float


@dataclass
class DiagnosticTrace:
    stages: list[Stage] = field(default_factory=list)

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


@contextmanager
def capture(trace: DiagnosticTrace) -> Iterator[None]:
    token = _current.set(trace)
    try:
        yield
    finally:
        _current.reset(token)


def traced(name: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            trace = _current.get()
            if trace is None:
                return function(*args, **kwargs)
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                trace.stages.append(Stage(name, (perf_counter() - started) * 1000))

        return wrapped

    return decorate
