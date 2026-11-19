"""唯一页计划：冻结背景和在线补页不能再次调用混合召回入口。"""

from contextlib import contextmanager

import pytest

from relationship_query.contracts import SearchRequest
from relationship_query.domain.graph_relations import NeighborBlock
from relationship_query.services.materialized_query import MaterializedQueryService
from relationship_query.services.query import QueryError
from tests import test_uuid_query_performance as paging

paged_repository = paging.paged_repository


class Traversal:
    def __init__(self, ids):
        self.ids = ids
        self.positions = []
        self.chain_calls = []

    def block(self, after, size=128):
        self.positions.append(after)
        pending = [key for key in self.ids if after is None or key > after]
        return NeighborBlock(ids=tuple(pending[:size]), has_more=len(pending) > size)

    def chains(self, ids):
        self.chain_calls.append(ids)
        return {key: ["p:expert:1", key] for key in ids}


class Engine:
    cache = None

    def __init__(self, view):
        self.view, self.calls = view, 0

    @contextmanager
    def open_traversal(self, reference, scope, max_hops, budget):
        self.calls += 1
        assert set(scope.model_dump()) == set(type(scope).model_fields)
        assert not hasattr(scope, "organization_ids")
        yield self.view


@pytest.mark.parametrize("sparse", [False, True])
def test_page_plan_scans_blocks_filters_background_and_fills_deleted_endpoints(
    paged_repository, monkeypatch, sparse
):
    repository, ids = paged_repository
    repository.storage = "sqlite-numeric-source"
    view = Traversal(ids)
    engine = Engine(view)
    service = MaterializedQueryService(repository, engine)

    def forbidden(*args):
        pytest.fail("新页计划重新调用了混合search_ids入口")

    monkeypatch.setattr(repository, "search_ids", forbidden)
    deleted = set(ids[1100:1110] if sparse else ids[:140])
    monkeypatch.setattr(
        repository, "select_active_endpoints", lambda keys: [k for k in keys if k not in deleted]
    )
    request = SearchRequest(
        max_hops=4, page_size=17, organization_ids=["org:late"] if sparse else []
    )
    plan = service.select_page(request, "p:expert:1")
    expected = [k for k in (ids[1100:] if sparse else ids) if k not in deleted][:18]
    assert plan.ids == tuple(expected[:17])
    assert plan.probe_id == expected[17] and plan.has_more
    assert engine.calls == 1 and len(view.positions) > 1
    assert view.chain_calls == [expected[:17]]
    assert dict(plan.chains) == {key: ("p:expert:1", key) for key in expected[:17]}


def test_empty_view_cannot_claim_more_and_old_cursor_is_rejected(paged_repository):
    repository, _ = paged_repository
    view = Traversal([])
    view.block = lambda *args: NeighborBlock(ids=(), has_more=True)
    service = MaterializedQueryService(repository, Engine(view))
    with pytest.raises(QueryError) as rejected:
        service.select_page(SearchRequest(), "p:expert:1")
    assert rejected.value.code == "GRAPH_INTEGRITY"
    old = service._encode_cursor("p:resume:000017", "old-cursor-v3")
    with pytest.raises(QueryError) as rejected:
        service.select_page(SearchRequest(cursor=old), "p:expert:1")
    assert rejected.value.code == "INVALID_CURSOR"
