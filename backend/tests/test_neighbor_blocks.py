"""候选覆盖范围与稀疏SQL筛选的分页语义，缓存仍共用原有字节及条数配额。"""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from relationship_query.contracts import SearchRequest
from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.uuid_graph import MaterializedGraphRepository
from relationship_query.runtime.relation_cache import RelationCache
from relationship_query.services.query import QueryError

from .test_live_people import live as live
from .test_real_query import real_release as real_release
from .test_uuid_query_performance import paged_repository as paged_repository


def budget():
    return PathBudget(5000, 5000)


def graph_for(ids, cache=None):
    graph = object.__new__(MaterializedGraphRepository)
    graph.cache = cache if cache is not None else RelationCache("release-v1")
    graph.client = SimpleNamespace(check_version=lambda budget: None)
    calls = []

    def read(reference, scope, after, budget, size):
        calls.append(after)
        return [key for key in ids if after is None or key > after][: size + 1]

    graph._neighbor_ids = read
    return graph, calls


def test_suffix_keeps_more_flag_even_when_less_than_full_block():
    ids = [f"p:{i:03d}" for i in range(260)]
    graph, calls = graph_for(ids)
    request = SearchRequest()
    first = graph.neighbor_block("root", request, None, budget())
    assert first.ids == tuple(ids[:128]) and first.has_more
    suffix = graph.neighbor_block("root", request, ids[120], budget())
    assert suffix.ids == tuple(ids[121:128]) and suffix.has_more
    next_block = graph.neighbor_block("root", request, suffix.ids[-1], budget())
    assert next_block.ids == tuple(ids[128:256]) and next_block.has_more
    last = graph.neighbor_block("root", request, ids[255], budget())
    assert last.ids == tuple(ids[256:]) and not last.has_more
    assert graph.neighbor_block("root", request, ids[-1], budget()).ids == ()
    assert graph.neighbor_block("root", request, "p:999", budget()).ids == ()
    assert calls == [None, ids[127], ids[255]]


@pytest.mark.parametrize("sparse", [False, True])
def test_paging_and_background_filters_cross_blocks_without_retraversal(paged_repository, sparse):
    repository, ids = paged_repository
    graph, calls = graph_for(ids)
    repository.graph = graph
    expected = ids[1100:] if sparse else [key for key in ids if key != ids[1000]]
    for size in (17, 1, 50):
        request = SearchRequest(organization_ids=["org:late"] if sparse else [], page_size=size)
        after, found = None, []
        while True:
            page = repository.search_ids(request, "p:expert:1", after)
            found.extend(page[:size])
            if len(page) <= size:
                break
            after = page[size - 1]
        assert found == expected
        assert len(calls) == 9
    # 背景变化复用原关系候选；稀疏／无匹配时仍读完范围，不误报末页。
    no_match = SearchRequest(school_ids=["school:no-match"], page_size=17)
    assert repository.search_ids(no_match, "p:expert:1", None) == []
    assert len(calls) == 9


def test_blocks_separate_release_reference_scope_and_size():
    graph, calls = graph_for([f"p:{i:03d}" for i in range(260)])
    base = SearchRequest(max_hops=4)
    graph.neighbor_block("root", base, None, budget())
    graph.neighbor_block(
        "root", base.model_copy(update={"school_ids": ["school:background"]}), "p:010", budget()
    )
    assert len(calls) == 1
    for scope in (
        base.model_copy(update={"max_hops": 3}),
        base.model_copy(update={"require_same_school": True}),
        base.model_copy(update={"relation_type": "same_company_overlap"}),
        base.model_copy(update={"relation_start_month": 202001}),
        base.model_copy(update={"relation_organization_ids": ["company:2"]}),
    ):
        graph.neighbor_block("root", scope, "p:010", budget())
    graph.neighbor_block("other-root", base, "p:010", budget())
    graph.neighbor_block("root", base, "p:010", budget(), size=8)
    assert len(calls) == 8
    graph.cache = RelationCache("release-v2")
    graph.neighbor_block("root", base, "p:010", budget())
    assert len(calls) == 9


def test_range_cache_expiry_eviction_overwrite_and_close_remove_metadata():
    now = [0]
    cache = RelationCache("release", max_bytes=700, ttl_seconds=10, clock=lambda: now[0])
    for index in range(100):
        cache.store_range(index, None, "p:2", False, {"ids": ["p:1", "p:2"]}, budget())
        cache.store("ordinary", [index], budget())
        assert cache._bytes <= 700
        indexed = {key for group in cache._ranges.values() for key in group}
        assert indexed == set(cache._coverage) <= set(cache._entries)
        assert cache._bytes == sum(
            len(key) + len(payload) + cache._coverage_size(cache._coverage.get(key))
            for key, (_, payload) in cache._entries.items()
        )
    value = cache.covering(99, "p:1", budget())
    assert value == {"ids": ["p:1", "p:2"]}
    value["ids"].append("caller mutation")
    assert cache.covering(99, "p:1", budget()) == {"ids": ["p:1", "p:2"]}
    now[0] = 11
    assert cache.covering(99, "p:1", budget()) is None
    cache.close()
    assert not cache._coverage and not cache._ranges and cache._bytes == 0
    cache.store_range("closed", None, "p:2", True, ["p:1"], budget())
    assert not cache._entries


def test_disabled_cache_and_failed_or_unsorted_reads_do_not_leave_covering_results():
    graph, calls = graph_for(["p:1", "p:2"], RelationCache("disabled", max_bytes=0))
    for _ in range(2):
        graph.neighbor_block("root", SearchRequest(), None, budget())
    assert len(calls) == 2 and not graph.cache._ranges
    graph.cache = RelationCache("fresh")
    graph._neighbor_ids = lambda *args: ["p:2", "p:1"]
    with pytest.raises(QueryError) as rejected:
        graph.neighbor_block("root", SearchRequest(), None, budget())
    assert rejected.value.code == "GRAPH_INTEGRITY" and not graph.cache._ranges


def test_range_index_has_same_entry_bound_and_concurrent_overwrites_remain_consistent():
    cache = RelationCache("bounded", max_bytes=8 * 1024 * 1024)
    for index in range(1100):
        cache.store_range(index, None, "p:2", False, ["p:1"], budget())
    assert len(cache._entries) == len(cache._coverage) == len(cache._ranges) == 1024
    assert cache.covering(0, None, budget()) is None

    def write(index):
        for end in ("p:3", "p:4", "p:5"):
            cache.store_range(index % 3, None, end, False, [end], budget())

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(32)))
    assert cache._bytes == sum(
        len(key) + len(payload) + cache._coverage_size(cache._coverage.get(key))
        for key, (_, payload) in cache._entries.items()
    )
    assert cache._bytes <= cache.max_bytes
    assert sum(map(len, cache._ranges.values())) == len(cache._coverage) <= 1024


def test_expired_specific_range_falls_back_to_valid_covering_range():
    now = [0]
    cache = RelationCache("release", clock=lambda: now[0], ttl_seconds=10)
    cache.store_range("group", "p:2", "p:5", False, ["specific"], budget())
    now[0] = 5
    cache.store_range("group", None, "p:8", False, ["broad"], budget())
    now[0] = 11
    assert cache.covering("group", "p:3", budget()) == ["broad"]
    assert len(cache._coverage) == 1


def test_cached_candidate_block_still_filters_live_person_deletion(live):
    graph, calls = graph_for(["p:resume:1"])
    live.repository.graph = graph
    request = SearchRequest()
    assert live.repository.search_ids(request, "p:expert:1", None) == ["p:resume:1"]
    with live.engine.begin() as connection:
        connection.execute(update(live.schema.tables["resume"]).values(deleted_at="2026-11-17"))
    assert live.repository.search_ids(request, "p:expert:1", None) == []
    assert calls == [None]
