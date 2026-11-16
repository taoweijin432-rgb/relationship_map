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
            self._entries.pop(key)
            self._bytes -= len(key) + len(payload)
            return None
        self._entries.move_to_end(key)
        return payload

    def _store(self, key: str, payload: bytes) -> None:
        size = len(key) + len(payload)
        if self._closed or size > min(self.max_bytes, 128 * 1024):
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._bytes -= len(key) + len(previous[1])
        # 键数量也有限制，字节计数外的字典开销不会无限增长。
        while self._entries and (self._bytes + size > self.max_bytes or len(self._entries) >= 1024):
            old_key, (_, old_payload) = self._entries.popitem(last=False)
            self._bytes -= len(old_key) + len(old_payload)
        self._entries[key] = (self.clock() + self.ttl, payload)
        self._bytes += size

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._entries.clear()
            self._bytes = 0
