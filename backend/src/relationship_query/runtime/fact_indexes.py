"""只在一次查询内复用已核验事实；不保存人物展示，也不跨请求保留。"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from relationship_query.contracts import FactView

Namespace = tuple[object, ...]
GraphFactKey = tuple[str, str, str, int]


@dataclass
class FactIndexes:
    graph: dict[tuple[Namespace, GraphFactKey], dict[str, Any]] = field(default_factory=dict)
    sql: dict[tuple[Namespace, str], FactView] = field(default_factory=dict)


_current: ContextVar[FactIndexes | None] = ContextVar("request_fact_indexes", default=None)


def current_fact_indexes() -> FactIndexes | None:
    return _current.get()


@contextmanager
def fact_indexes() -> Iterator[FactIndexes]:
    indexes = _current.get() or FactIndexes()
    token = _current.set(indexes)
    try:
        yield indexes
    finally:
        _current.reset(token)
