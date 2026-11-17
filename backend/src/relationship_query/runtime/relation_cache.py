"""进程内发布缓存：有界关系ID存储，异步协调器负责计算准入和同键等待。"""

import json
import os
from collections import OrderedDict
from collections.abc import Callable
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import TypeVar, cast

from relationship_query.domain.path_budget import PathBudget
from relationship_query.runtime.diagnostics import observe

T = TypeVar("T")


class RelationCache:
    def __init__(
        self,
        namespace: str,
        *,
        max_bytes: int = 8 * 1024 * 1024,
        ttl_seconds: float = 300,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.namespace, self.max_bytes, self.ttl, self.clock = (
            namespace,
            max_bytes,
            ttl_seconds,
            clock,
        )
        self._entries: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._ranges: dict[str, dict[str, tuple[str, str, bool]]] = {}
        self._coverage: dict[str, tuple[str, str, str, bool]] = {}
        self._lock = Lock()
        self._bytes = self.hits = self.misses = 0
        self._closed = False

    @classmethod
    def configured(cls, namespace: str) -> "RelationCache":
        maximum = int(os.environ.get("RELATIONSHIP_RELATION_CACHE_BYTES", 8 * 1024 * 1024))
        if not 0 <= maximum <= 64 * 1024 * 1024:
            raise ValueError("关系缓存容量必须在0至64MiB之间")
        return cls(namespace, max_bytes=maximum)

    def get_or_compute(self, arguments: object, budget: PathBudget, compute: Callable[[], T]) -> T:
        cached = self.lookup(arguments, budget)
        if cached is not None:
            return cast(T, cached)
        result = compute()
        self.store(arguments, result, budget)
        return result

    def key(self, arguments: object) -> str:
        return sha256(json.dumps([self.namespace, arguments], sort_keys=True).encode()).hexdigest()

    def lookup(self, arguments: object, budget: PathBudget) -> object | None:
        budget.check()
        with self._lock:
            payload = None if self._closed else self._get(self.key(arguments))
            if payload is not None:
                self.hits += 1
            else:
                self.misses += 1
        observe("relation_cache.hit" if payload is not None else "relation_cache.miss")
        return self._decode(payload, budget) if payload is not None else None

    def store(self, arguments: object, result: object, budget: PathBudget) -> None:
        budget.check()
        payload = json.dumps(result, separators=(",", ":")).encode()
        budget.check()
        with self._lock:
            self._store(self.key(arguments), payload)

    def covering(self, arguments: object, after: str | None, budget: PathBudget) -> object | None:
        """只扫描有界范围元信息，命中后才解码一个候选块。"""
        budget.check()
        group, cursor = self.key(["range-v1", arguments]), after or ""
        with self._lock:
            ranges = self._ranges.get(group, {})
            choices = sorted(
                (
                    (start, key)
                    for key, (start, end, complete) in ranges.items()
                    if start <= cursor and (complete or cursor < end)
                ),
                reverse=True,
            )
            payload = None
            for _, key in choices:
                payload = self._get(key)
                if payload is not None:
                    break
            self.hits += int(payload is not None)
            self.misses += int(payload is None)
        observe("relation_cache.range_hit" if payload is not None else "relation_cache.range_miss")
        return self._decode(payload, budget) if payload is not None else None

    def store_range(
        self,
        arguments: object,
        after: str | None,
        through: str,
        complete: bool,
        result: object,
        budget: PathBudget,
    ) -> None:
        budget.check()
        payload = json.dumps(result, separators=(",", ":")).encode()
        budget.check()
        coverage = (self.key(["range-v1", arguments]), after or "", through, complete)
        with self._lock:
            self._store(self.key(["range-v1", arguments, after]), payload, coverage)

    @staticmethod
    def _decode(payload: bytes, budget: PathBudget) -> object:
        result = json.loads(payload)
        budget.check()
        return result

    def _get(self, key: str) -> bytes | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires, payload = entry
        if expires <= self.clock():
            self._discard(key)
            return None
        self._entries.move_to_end(key)
        return payload

    def _store(
        self, key: str, payload: bytes, coverage: tuple[str, str, str, bool] | None = None
    ) -> None:
        size = len(key) + len(payload) + self._coverage_size(coverage)
        if self._closed or size > min(self.max_bytes, 128 * 1024):
            return
        self._discard(key)
        # 键数量也有限制，字节计数外的字典开销不会无限增长。
        while self._entries and (self._bytes + size > self.max_bytes or len(self._entries) >= 1024):
            self._discard(next(iter(self._entries)))
        self._entries[key] = (self.clock() + self.ttl, payload)
        self._bytes += size
        if coverage is not None:
            group, start, end, complete = coverage
            self._coverage[key] = coverage
            self._ranges.setdefault(group, {})[key] = (start, end, complete)

    @staticmethod
    def _coverage_size(coverage: tuple[str, str, str, bool] | None) -> int:
        return len(json.dumps(coverage).encode()) if coverage is not None else 0

    def _discard(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        coverage = self._coverage.pop(key, None)
        self._bytes -= len(key) + len(entry[1]) + self._coverage_size(coverage)
        if coverage is not None:
            group = coverage[0]
            self._ranges[group].pop(key)
            if not self._ranges[group]:
                self._ranges.pop(group)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._entries.clear()
            self._ranges.clear()
            self._coverage.clear()
            self._bytes = 0
