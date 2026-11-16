"""进程内发布缓存：只存JSON兼容的关系ID结果，限制大小并合并同键计算。"""

import json
import os
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import TypeVar, cast

from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded

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
        self._pending: dict[str, Future[bytes]] = {}
        self._lock = Lock()
        self._bytes = self.hits = self.misses = self.coalesced = 0
        self._closed = False

    @classmethod
    def configured(cls, namespace: str) -> "RelationCache":
        maximum = int(os.environ.get("RELATIONSHIP_RELATION_CACHE_BYTES", 8 * 1024 * 1024))
        if not 0 <= maximum <= 64 * 1024 * 1024:
            raise ValueError("关系缓存容量必须在0至64MiB之间")
        return cls(namespace, max_bytes=maximum)

    def get_or_compute(self, arguments: object, budget: PathBudget, compute: Callable[[], T]) -> T:
        budget.check()
        key = sha256(json.dumps([self.namespace, arguments], sort_keys=True).encode()).hexdigest()
        with self._lock:
            payload = self._get(key)
            if payload is not None:
                self.hits += 1
                return cast(T, self._decode(payload, budget))
            disabled = self._closed or self.max_bytes == 0
            pending = self._pending.get(key)
            owner = pending is None
            if not disabled and owner and len(self._pending) < 32:
                pending = self._pending[key] = Future()
                self.misses += 1
            elif not disabled and pending is not None:
                self.coalesced += 1
        if disabled or pending is None:
            return compute()
        if not owner:
            try:
                payload = pending.result(timeout=max(0, budget.deadline - budget.clock()))
            except TimeoutError:
                raise PathBudgetExceeded("time_limit") from None
            budget.check()
            return cast(T, self._decode(payload, budget))
        try:
            result = compute()
            budget.check()
            payload = json.dumps(result, separators=(",", ":")).encode()
            with self._lock:
                self._store(key, payload)
            pending.set_result(payload)
            return result
        except BaseException as error:
            pending.set_exception(error)
            raise
        finally:
            with self._lock:
                self._pending.pop(key, None)

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
        # 键数量也有限制，字节计数外的字典和Future开销不会无限增长。
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
