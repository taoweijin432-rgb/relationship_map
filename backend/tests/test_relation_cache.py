"""缓存版本／条件隔离、内存边界及并发等待与失败恢复。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from time import sleep

import pytest

from relationship_query.contracts import SearchRequest
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.uuid_graph import relation_scope_key
from relationship_query.runtime.relation_cache import RelationCache
from relationship_query.services.query import QueryError


def budget():
    return PathBudget(3000, 100)


def test_cache_returns_independent_values_and_expires():
    now = [0]
    cache = RelationCache("release-a", ttl_seconds=10, clock=lambda: now[0])
    calls = []

    def compute():
        calls.append(1)
        return {"p:2": ["p:1", "p:2"]}

    result = cache.get_or_compute("key", budget(), compute)
    result["p:2"].append("caller mutation")
    assert cache.get_or_compute("key", budget(), compute) == {"p:2": ["p:1", "p:2"]}
    assert len(calls) == 1
    now[0] = 11
    cache.get_or_compute("key", budget(), compute)
    assert len(calls) == 2


def test_memory_limit_and_oversized_result_do_not_change_results():
    cache = RelationCache("release", max_bytes=120)
    for key in range(100):
        assert cache.get_or_compute(key, budget(), lambda: [str(key)]) == [str(key)]
        assert cache._bytes <= 120
    assert len(cache._entries) == 1
    large = ["x" * 1024]
    assert cache.get_or_compute("large", budget(), lambda: large) == large
    assert cache._bytes <= 120


def test_same_key_is_computed_once_for_concurrent_callers():
    cache = RelationCache("release")
    barrier, lock = Barrier(4), Lock()
    calls = []

    def compute():
        with lock:
            calls.append(1)
        sleep(0.03)
        return ["p:1", "p:2"]

    def worker(_):
        barrier.wait(3)
        return cache.get_or_compute("same", budget(), compute)

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(worker, range(4))) == [["p:1", "p:2"]] * 4
    assert len(calls) == 1 and cache.coalesced == 3


def test_waiter_timeout_does_not_cancel_other_callers_computation():
    cache = RelationCache("release")
    started, finish = Event(), Event()

    def compute():
        started.set()
        assert finish.wait(3)
        return ["p:2"]

    with ThreadPoolExecutor(max_workers=1) as executor:
        owner = executor.submit(cache.get_or_compute, "same", budget(), compute)
        assert started.wait(3)
        with pytest.raises(PathBudgetExceeded):
            cache.get_or_compute("same", PathBudget(5, 100), lambda: pytest.fail("duplicate"))
        finish.set()
        assert owner.result() == ["p:2"]
    assert cache.get_or_compute("same", budget(), lambda: pytest.fail("not cached")) == ["p:2"]


def test_failures_are_not_cached_and_waiters_receive_explicit_error():
    cache = RelationCache("release")
    started, finish = Event(), Event()

    def failure():
        started.set()
        assert finish.wait(3)
        raise QueryError("GRAPH_UNAVAILABLE", "test-only", 503)

    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(cache.get_or_compute, "same", budget(), failure)
        assert started.wait(3)
        waiter = executor.submit(cache.get_or_compute, "same", budget(), lambda: ["unexpected"])
        sleep(0.02)
        finish.set()
        for task in (owner, waiter):
            with pytest.raises(QueryError) as error:
                task.result()
            assert error.value.code == "GRAPH_UNAVAILABLE"
    assert not cache._pending and not cache._entries
    assert cache.get_or_compute("same", budget(), lambda: ["recovered"]) == ["recovered"]


def test_release_change_and_disable_or_shutdown_cannot_reuse_previous_results():
    first, second = RelationCache("release-a"), RelationCache("release-b")
    assert first.get_or_compute("same", budget(), lambda: ["old"]) == ["old"]
    assert second.get_or_compute("same", budget(), lambda: ["new"]) == ["new"]
    first.close()
    assert not first._entries and first._bytes == 0
    assert first.get_or_compute("same", budget(), lambda: ["after close"]) == ["after close"]
    disabled = RelationCache("release", max_bytes=0)
    assert disabled.get_or_compute("same", budget(), lambda: ["live"]) == ["live"]
    assert not disabled._entries


def test_cache_scope_ignores_only_background_and_display_paging_fields():
    base = SearchRequest(max_hops=4)
    background = SearchRequest(max_hops=4, school_ids=["school:1"], page_size=1)
    assert relation_scope_key(base) == relation_scope_key(background)
    assert relation_scope_key(base) != relation_scope_key(SearchRequest(max_hops=3))
    assert relation_scope_key(base) != relation_scope_key(
        SearchRequest(relation_type="same_school")
    )
    same_major = SearchRequest(relation_type="same_major", max_hops=4)
    assert relation_scope_key(same_major) != relation_scope_key(
        same_major.model_copy(update={"require_same_school": True})
    )


def test_cached_chain_keeps_live_person_reads_and_deletion_errors():
    from types import SimpleNamespace

    from relationship_query.domain.models import Person
    from relationship_query.infrastructure.uuid_graph import MaterializedReader

    reads, graph_calls = [], []
    state = {"name": "current name", "deleted": False}

    def execute(*args):
        graph_calls.append(1)
        return [{"person_id": "p:2", "person_ids": ["p:1", "p:2"]}]

    def people(ids):
        reads.append(ids)
        if state["deleted"]:
            raise QueryError("PERSON_SOURCE_CHANGED", "test deletion", 503)
        return [Person(id="p:2", name=state["name"], city="", headline="", sources=["expert"])]

    reader = MaterializedReader(
        None,
        SimpleNamespace(execute=execute),
        budget(),
        people,
        RelationCache("release"),
    )
    filters = SearchRequest()
    assert reader.shortest_connections("p:1", ["p:2"], filters)["p:2"] == ["p:1", "p:2"]
    assert reader.persons(["p:2"])["p:2"].name == "current name"
    state["name"] = "updated name"
    reader.shortest_connections("p:1", ["p:2"], filters)
    assert reader.persons(["p:2"])["p:2"].name == "updated name"
    state["deleted"] = True
    with pytest.raises(QueryError) as error:
        reader.persons(["p:2"])
    assert error.value.code == "PERSON_SOURCE_CHANGED"
    assert len(graph_calls) == 1 and len(reads) == 3


@pytest.mark.parametrize("value", ["-1", "999999999", "invalid"])
def test_invalid_cache_configuration_is_not_silently_unlimited(monkeypatch, value):
    monkeypatch.setenv("RELATIONSHIP_RELATION_CACHE_BYTES", value)
    with pytest.raises(ValueError):
        RelationCache.configured("release")
