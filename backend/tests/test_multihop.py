"""单人物多跳契约、预算隔离与独立原生图人工链回归。"""

import json
import os
import re
from pathlib import Path
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from relationship_query.app import create_app
from relationship_query.contracts import SearchRequest
from relationship_query.domain.path_budget import relation_query_budget, shared_relation_budget
from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
)
from relationship_query.infrastructure.uuid_graph import connection_match
from relationship_query.update.artifacts import write_json
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import SourceSnapshot
from relationship_query.update.projection import NumericProjectionAdapter
from relationship_query.update.service import UpdateProgram
from relationship_query.update.store import UpdateStore
from relationship_query.update.target import NebulaTarget

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value", [0, 5, 1.5, "2", True])
def test_depth_rejects_invalid_values(value):
    with pytest.raises(ValidationError):
        SearchRequest(max_hops=value)


def test_depth_defaults_and_sql_capability(client):
    assert SearchRequest().max_hops == 1
    assert client.get("/api/v1/meta").json()["max_relation_hops"] == 1
    person = client.get("/api/v1/persons/suggest").json()["items"][0]["id"]
    response = client.post(f"/api/v1/persons/{person}/relations/search", json={"max_hops": 2})
    assert response.status_code == 422 and response.json()["code"] == "UNSUPPORTED_MULTI_HOP"
    response = client.post("/api/v1/persons/search", json={"max_hops": 2})
    assert response.status_code == 422 and response.json()["code"] == "REFERENCE_REQUIRED"


def test_shared_budget_nesting_and_cleanup():
    before = relation_query_budget()
    with pytest.raises(RuntimeError), shared_relation_budget() as outer:
        with shared_relation_budget() as inner:
            assert inner is outer
        assert relation_query_budget() is outer
        raise RuntimeError("test-only")
    assert relation_query_budget() is not outer
    assert before is not outer


@pytest.mark.parametrize("depth", [1, 2, 3, 4])
def test_templates_apply_scope_and_exclude_repeated_people(depth):
    statement, vertices = connection_match(
        "p:expert:1",
        SearchRequest(
            relation_type="same_company_overlap",
            relation_organization_ids=["company:1"],
            relation_start_month=202001,
            relation_end_month=202212,
            min_overlap_months=6,
        ),
        depth,
    )
    assert len(vertices) == depth + 1
    for index in range(depth):
        assert f"r{index}.entity_vid" in statement
        assert f"r{index}.overlap_start_month" in statement
    assert "id(v0)!=id(v1)" in statement
    for index in range(1, depth):
        assert f"NOT (id(v{index + 1}) IN connection_ids)" in statement
        assert f"WITH v{index},min(" in statement
    assert "WITH DISTINCT v0," not in statement


@pytest.mark.parametrize("depth", [2, 3, 4])
def test_school_prerequisite_recall_folds_each_frontier(depth):
    statement, _ = connection_match(
        "p:expert:1",
        SearchRequest(relation_type="same_major", require_same_school=True),
        depth,
        paths=False,
    )
    for index in range(1, depth):
        assert f"WITH DISTINCT v{index}" in statement
    assert statement.count("-[:same_school]-") == depth


def test_native_traversal_filters_cursor_after_all_steps():
    from types import SimpleNamespace

    from relationship_query.domain.path_budget import PathBudget
    from relationship_query.infrastructure.uuid_graph import MaterializedGraphRepository

    calls = []

    def execute(statement, budget, maximum):
        calls.append(statement)
        assert maximum == 129
        return [{"person_id": "p:expert:9"}]

    graph = object.__new__(MaterializedGraphRepository)
    from relationship_query.runtime.relation_cache import RelationCache

    graph.cache = RelationCache("test-only", max_bytes=0)
    graph.client = SimpleNamespace(execute=execute)
    scope = SearchRequest(
        relation_type="same_company_overlap",
        max_hops=4,
        relation_organization_ids=["company:1"],
        relation_start_month=202001,
        relation_end_month=202212,
        min_overlap_months=6,
    )
    block = graph.neighbor_block("p:expert:1", scope, "p:expert:8", PathBudget(5000, 5000))
    assert block.ids == ("p:expert:9",) and not block.has_more
    traversal, output = calls[0].split(" | ", 1)
    assert "GO 1 TO 4 STEPS" in traversal and "BIDIRECT" in traversal
    assert "properties(edge).entity_vid" in traversal
    assert "properties(edge).overlap_start_month" in traversal
    assert "p:expert:8" not in traversal
    assert '$-.person_id>"p:expert:8"' in output


def chain_snapshot(contract_data):
    """显式链与菱形备选构造，无生产路径函数参与预期。"""
    baseline = json.loads(
        (ROOT / "data/mysql-update-latest/run-v3-final/baseline.json").read_text()
    )
    original = baseline["tables"]
    tables = {name: [] for name in original}
    names = {logical: table["physical"] for logical, table in contract_data["tables"].items()}
    people = [
        ("expert", 1),
        ("resume", 1),
        ("expert", 2),
        ("resume", 2),
        ("expert", 3),
        ("resume", 3),
        ("resume", 4),
        ("expert", 4),
    ]
    for source, person_id in people:
        key = names[f"person_{source}"]
        row = dict(
            original[key][0],
            id=person_id,
            name=f"虚构链人物{source}{person_id}",
            serial_number=f"{source}-{person_id}",
        )
        tables[key].append(row)
    links = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (0, 6), (6, 2)]
    for entity_id, (left, right) in enumerate(links, 1):
        entity_key = names["company"]
        tables[entity_key].append(
            dict(
                original[entity_key][0],
                id=entity_id,
                uuid=str(uuid5(NAMESPACE_URL, f"multihop-company-{entity_id}")),
                company_code=f"MULTI-{entity_id}",
                standard_name=f"虚构链公司{entity_id}",
            )
        )
        for index in (left, right):
            source, person_id = people[index]
            row_id = 100 + len(tables[names["edge_mapping"]])
            key = names[f"work_{source}"]
            tables[key].append(
                dict(
                    original[key][0],
                    id=row_id,
                    **{f"{source}_id": person_id},
                    start_date="2020-01-01T00:00:00",
                    end_date="2022-12-31T00:00:00",
                    is_employed=2,
                    position_title="虚构工程师",
                )
            )
            edge_key = names["edge_mapping"]
            tables[edge_key].append(
                dict(
                    original[edge_key][0],
                    id=row_id,
                    source_system=source,
                    source_person_id=person_id,
                    source_table=key.split(".")[-1],
                    source_field_id=row_id,
                    standard_entity_id=entity_id,
                )
            )
    key = names["school"]
    tables[key].append(dict(original[key][0], id=1))
    for person_id in (3, 4):
        key = names["education_expert"]
        tables[key].append(dict(original[key][0], id=person_id, expert_id=person_id))
        edge_key = names["edge_mapping"]
        tables[edge_key].append(
            dict(
                original[edge_key][0],
                id=500 + person_id,
                edge_type="studied_at",
                source_person_id=person_id,
                source_field_id=person_id,
                source_table=key.split(".")[-1],
                source_field="school_name",
                standard_entity_id=1,
            )
        )
    for row_id in range(1000, 1024):
        key = names["work_expert"]
        tables[key].append(dict(tables[key][0], id=row_id))
        key = names["edge_mapping"]
        tables[key].append(dict(tables[key][0], id=row_id, source_field_id=row_id))
    baseline["tables"] = tables
    return SourceSnapshot.model_validate(baseline)


@pytest.fixture(scope="module")
def native_chain(tmp_path_factory):
    if os.environ.get("RELATIONSHIP_MULTIHOP_NATIVE") != "1":
        pytest.skip("显式启用独立原生多跳图")
    directory = tmp_path_factory.mktemp("multihop-native")
    contract_data = json.loads((ROOT / "data/balanced-frontend/run-v2/contract.json").read_text())
    contract_data["version"] += "-multihop-test"
    contract = SourceContract.model_validate(contract_data)
    write_json(directory / "contract.json", contract.model_dump(mode="json"))
    store = UpdateStore(directory / "state", contract, create=True)
    program = UpdateProgram(store, NumericProjectionAdapter(contract))
    try:
        program.bootstrap(chain_snapshot(contract_data), 202611)
        program.process(202611, NebulaTarget(DEFAULT_CREDENTIALS))
        with TestClient(create_app(numeric_release_store=directory / "state")) as client:
            client.app.state.multihop_observations = []
            yield client
            selected = os.environ.get("RELATIONSHIP_MULTIHOP_REPORT_DIR")
            if selected:
                write_json(
                    Path(selected) / "native-observations.json",
                    {
                        "data_mode": "mock",
                        "people": 8,
                        "scope": "独立小图、顺序HTTP分页，含SDK连接与认证，无生产容量结论",
                        "observations": client.app.state.multihop_observations,
                        "ephemeral_space": True,
                    },
                )
    finally:
        with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
            for path in directory.glob("state/releases/*/*/build-resource.json"):
                space = json.loads(path.read_text())["space"]
                assert re.fullmatch(r"relationship_lab_sync_[0-9a-f]{12}", space)
                query(session, f"DROP SPACE IF EXISTS `{space}`")
            for path in directory.glob("state/releases/*/*/reader-credentials.json"):
                name = json.loads(path.read_text())["username"]
                assert re.fullmatch(r"[a-zA-Z0-9_]+", name)
                query(session, f"DROP USER IF EXISTS {name}")


def call(client, endpoint, body):
    response = client.post(f"/api/v1{endpoint}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("depth", [1, 2, 3, 4])
def test_native_relation_page_does_not_reenter_mixed_recall(native_chain, monkeypatch, depth):
    def forbidden(*args):
        pytest.fail("关联页重新调用旧混合召回入口")

    monkeypatch.setattr(native_chain.app.state.query_service.repository, "search_ids", forbidden)
    data = call(
        native_chain,
        "/persons/p:expert:1/relations/search",
        {"max_hops": depth, "page_size": 2},
    )
    assert len(data["items"]) == 2


@pytest.mark.parametrize("depth", [1, 2, 3, 4])
def test_native_combined_details_preserve_scoped_connection(native_chain, depth):
    filters = {"max_hops": depth, "relation_type": "same_company_overlap"}
    reference, candidate = "p:expert:1", "p:expert:3"
    details = call(
        native_chain,
        f"/persons/{candidate}/details",
        {"reference_id": reference, "filters": filters},
    )
    facts = native_chain.get(f"/api/v1/persons/{candidate}/facts").json()
    proof = call(
        native_chain,
        "/relations/evidence/search",
        {"reference_id": reference, "candidate_id": candidate, "filters": filters},
    )
    assert details["person"] == facts["person"] == proof["candidate"]
    assert details["facts"] == facts["items"]
    assert details["reference"] == proof["reference"]
    assert details["evidence"] == proof["items"]
    assert details["connection"] == proof["connection"]


@pytest.mark.parametrize(
    "depth,expected",
    [
        (1, ["p:resume:1", "p:resume:4"]),
        (2, ["p:expert:2", "p:resume:1", "p:resume:4"]),
        (3, ["p:expert:2", "p:resume:1", "p:resume:2", "p:resume:4"]),
        (4, ["p:expert:2", "p:expert:3", "p:resume:1", "p:resume:2", "p:resume:4"]),
    ],
)
def test_native_exact_depths_pagination_and_simple_paths(
    native_chain, depth, expected, monkeypatch
):
    graph = native_chain.app.state.query_service.graph
    execute = graph.client.execute
    counters = {"graph_calls": 0, "graph_returned_rows": 0}

    def counted(*args, **kwargs):
        rows = execute(*args, **kwargs)
        counters["graph_calls"] += 1
        counters["graph_returned_rows"] += len(rows)
        return rows

    monkeypatch.setattr(graph.client, "execute", counted)
    started = perf_counter()
    filters = {"max_hops": depth, "relation_type": "same_company_overlap", "page_size": 2}
    actual = []
    while True:
        data = call(native_chain, "/persons/p:expert:1/relations/search", filters)
        for item in data["items"]:
            actual.append(item["person"]["id"])
            if depth > 1:
                chain = item["connection"]["person_ids"]
                assert len(chain) == len(set(chain))
                assert len(chain) <= depth + 1
        if not data["has_more"]:
            break
        filters["cursor"] = data["next_cursor"]
    assert actual == expected
    native_chain.app.state.multihop_observations.append(
        {
            "max_hops": depth,
            "page_size": 2,
            "people_returned": len(actual),
            "elapsed_ms_all_pages": round((perf_counter() - started) * 1000, 3),
            **counters,
        }
    )


def test_native_shortest_tie_detail_export_expand_and_filters(native_chain):
    filters = {"max_hops": 4, "relation_type": "same_company_overlap", "source": "expert"}
    result = call(native_chain, "/persons/p:expert:1/relations/search", filters)
    assert [i["person"]["id"] for i in result["items"]] == ["p:expert:2", "p:expert:3"]
    chain = result["items"][1]["connection"]["person_ids"]
    assert chain == ["p:expert:1", "p:resume:1", "p:expert:2", "p:resume:2", "p:expert:3"]
    detail = call(
        native_chain,
        "/relations/evidence/search",
        {
            "reference_id": "p:expert:1",
            "candidate_id": "p:expert:3",
            "filters": filters,
        },
    )
    assert detail["items"] == []
    assert detail["connection"]["person_ids"] == chain
    assert len(detail["connection"]["segments"]) == 4
    assert detail["connection"]["segments"][0]["evidence_truncated"]
    exported = call(
        native_chain,
        "/exports/persons",
        {
            "reference_id": "p:expert:1",
            "filters": filters,
            "data_version": result["data_version"],
            "expected_person_ids": [i["person"]["id"] for i in result["items"]],
        },
    )
    assert exported["items"][1]["connection_detail"] == detail["connection"]
    expanded = call(native_chain, "/graph/expand", {"person_id": "p:expert:1", "filters": filters})
    assert "p:expert:3" in {n["id"] for n in expanded["graph"]["nodes"]}
    reverse = call(
        native_chain,
        "/relations/evidence/search",
        {
            "reference_id": "p:expert:3",
            "candidate_id": "p:expert:1",
            "filters": filters,
        },
    )
    assert reverse["connection"]["person_ids"] == chain[::-1]
    mixed = call(native_chain, "/persons/p:resume:2/relations/search", {"max_hops": 2})
    assert "p:expert:4" in {i["person"]["id"] for i in mixed["items"]}
    scoped = call(
        native_chain,
        "/persons/p:expert:1/relations/search",
        {
            **filters,
            "relation_organization_ids": ["company:1"],
        },
    )
    assert not scoped["items"]
    background = call(
        native_chain,
        "/persons/p:expert:1/relations/search",
        {
            **filters,
            "organization_ids": ["company:4"],
            "position_titles": ["虚构工程师"],
        },
    )
    assert [item["person"]["id"] for item in background["items"]] == ["p:expert:3"]
    dated = call(
        native_chain,
        "/persons/p:expert:1/relations/search",
        {
            **filters,
            "relation_start_month": 202101,
            "relation_end_month": 202112,
            "min_overlap_months": 13,
        },
    )
    assert not dated["items"]
    invalid_cursor = native_chain.post(
        "/api/v1/persons/p:expert:1/relations/search",
        json={
            **filters,
            "max_hops": 2,
            "cursor": native_chain.app.state.query_service._encode_cursor(
                "p:expert:2",
                native_chain.app.state.query_service._fingerprint(
                    SearchRequest(**filters), "p:expert:1"
                ),
            ),
        },
    )
    assert invalid_cursor.status_code == 422


@pytest.mark.parametrize("cache_enabled", [False, True])
def test_native_export_computes_shortest_connections_once(native_chain, monkeypatch, cache_enabled):
    from relationship_query.infrastructure.uuid_graph import MaterializedReader
    from relationship_query.runtime.relation_cache import RelationCache

    graph = native_chain.app.state.query_service.graph
    monkeypatch.setattr(
        graph, "cache", RelationCache("export-check", max_bytes=8192 if cache_enabled else 0)
    )

    filters = {"max_hops": 4, "relation_type": "same_company", "page_size": 20}
    page = call(native_chain, "/persons/p:expert:1/relations/search", filters)
    original = MaterializedReader.shortest_connections
    calls = []

    def record(self, *args, **kwargs):
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MaterializedReader, "shortest_connections", record)
    exported = call(
        native_chain,
        "/exports/persons",
        {
            "reference_id": "p:expert:1",
            "filters": filters,
            "data_version": page["data_version"],
            "expected_person_ids": [item["person"]["id"] for item in page["items"]],
        },
    )
    assert len(calls) == (0 if cache_enabled else 1)
    assert [item["person"]["id"] for item in exported["items"]] == [
        item["person"]["id"] for item in page["items"]
    ]
    assert [item["relations"] for item in exported["items"]] == [
        item["relations"] for item in page["items"]
    ]
    assert all(item["connection_detail"]["segments"] for item in exported["items"])


@pytest.mark.parametrize("cache_enabled", [False, True])
@pytest.mark.parametrize("operation", ["export", "expand"])
def test_native_direct_page_does_not_repeat_proof_or_fact_reads(
    native_chain, monkeypatch, cache_enabled, operation
):
    from unittest.mock import patch

    from relationship_query.infrastructure.uuid_graph import MaterializedReader
    from relationship_query.runtime.relation_cache import RelationCache

    service = native_chain.app.state.query_service
    monkeypatch.setattr(
        service.graph,
        "cache",
        RelationCache("direct-reuse", max_bytes=8192 if cache_enabled else 0),
    )
    filters = {"relation_type": "same_company", "page_size": 20}
    page = call(native_chain, "/persons/p:expert:1/relations/search", filters)
    calls = []
    original = MaterializedReader.read_proofs

    def record(self, *args, **kwargs):
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MaterializedReader, "read_proofs", record)
    with patch.object(
        service.repository, "fact_views", wraps=service.repository.fact_views
    ) as facts:
        if operation == "export":
            result = call(
                native_chain,
                "/exports/persons",
                {
                    "reference_id": "p:expert:1",
                    "filters": filters,
                    "data_version": page["data_version"],
                    "expected_person_ids": [item["person"]["id"] for item in page["items"]],
                },
            )
            for item in result["items"]:
                assert item["evidence"]
                assert item["relations"] == next(
                    row["relations"]
                    for row in page["items"]
                    if row["person"]["id"] == item["person"]["id"]
                )
        else:
            result = call(
                native_chain,
                "/graph/expand",
                {
                    "person_id": "p:expert:1",
                    "filters": filters,
                },
            )
            assert result["graph"] == page["graph"]
    assert len(calls) == facts.call_count == 1


@pytest.mark.parametrize("cache_enabled", [False, True])
@pytest.mark.parametrize("background", [{}, {"source": "resume"}])
def test_native_multihop_evidence_resolves_chain_once(
    native_chain, monkeypatch, cache_enabled, background
):
    from relationship_query.infrastructure.uuid_graph import MaterializedReader
    from relationship_query.runtime.relation_cache import RelationCache

    service = native_chain.app.state.query_service
    monkeypatch.setattr(
        service.graph,
        "cache",
        RelationCache("evidence-reuse", max_bytes=8192 if cache_enabled else 0),
    )
    original = MaterializedReader.shortest_connections
    calls = []

    def record(self, *args, **kwargs):
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MaterializedReader, "shortest_connections", record)
    result = call(
        native_chain,
        "/relations/evidence/search",
        {
            "reference_id": "p:expert:1",
            "candidate_id": "p:expert:3",
            "filters": {"max_hops": 4, "relation_type": "same_company", **background},
        },
    )
    assert len(calls) == (0 if background else 1)
    assert (result["connection"] is None) == bool(background)


def test_native_budget_and_integrity_fail_explicitly(native_chain, monkeypatch):
    from relationship_query.domain.path_budget import PathBudgetExceeded
    from relationship_query.services.query import QueryError

    def exceeded(*args, **kwargs):
        raise PathBudgetExceeded("time_limit")

    graph = native_chain.app.state.query_service.graph
    from relationship_query.runtime.relation_cache import RelationCache

    monkeypatch.setattr(graph, "cache", RelationCache("budget-check", max_bytes=0))
    with monkeypatch.context() as patch:
        patch.setattr(graph, "neighbor_block", exceeded)
        response = native_chain.post(
            "/api/v1/persons/p:expert:1/relations/search", json={"max_hops": 4}
        )
        assert response.status_code == 503 and response.json()["code"] == "GRAPH_QUERY_LIMIT"

    def missing(*args, **kwargs):
        raise QueryError("GRAPH_INTEGRITY", "test-only missing reference", 503)

    with monkeypatch.context() as patch:
        patch.setattr(
            "relationship_query.services.connections.GraphPathService._check_detail", missing
        )
        response = native_chain.post(
            "/api/v1/persons/p:expert:1/relations/search", json={"max_hops": 4}
        )
        assert response.status_code == 503 and response.json()["code"] == "GRAPH_INTEGRITY"
    with monkeypatch.context() as patch:

        def stale(*args, **kwargs):
            raise QueryError("GRAPH_VERSION_MISMATCH", "test-only changed graph", 409)

        patch.setattr(graph.client, "check_version", stale)
        response = native_chain.post(
            "/api/v1/persons/p:expert:1/relations/search", json={"max_hops": 4}
        )
        assert response.status_code == 409 and response.json()["code"] == "GRAPH_VERSION_MISMATCH"


def test_uuid_four_hop_compatibility():
    selected = os.environ.get("RELATIONSHIP_UUID_QUERY_TEST_DIR")
    if not selected:
        pytest.skip("显式选择UUID只读发布源")
    from relationship_query.infrastructure.source_releases import read_bundle

    bundle = read_bundle(Path(selected))
    with TestClient(
        create_app(
            source_manifest=bundle.directory / "manifest.json", source_mysql_url=bundle.mysql_url
        )
    ) as client:
        assert client.get("/api/v1/meta").json()["max_relation_hops"] == 4
        prior = set()
        for depth in range(1, 5):
            cursor = None
            found = set()
            while True:
                result = call(
                    client,
                    "/persons/p:expert:1/relations/search",
                    {
                        "max_hops": depth,
                        "cursor": cursor,
                        "relation_type": "same_company_overlap",
                    },
                )
                found.update(i["person"]["id"] for i in result["items"])
                assert "p:expert:1" not in found
                if not result["has_more"]:
                    break
                cursor = result["next_cursor"]
            assert prior <= found
            prior = found
        candidate = sorted(prior)[0]
        detail = call(
            client,
            "/relations/evidence/search",
            {
                "reference_id": "p:expert:1",
                "candidate_id": candidate,
                "filters": {"max_hops": 4, "relation_type": "same_company_overlap"},
            },
        )
        assert detail["connection"]["person_ids"][0] == "p:expert:1"
        assert detail["connection"]["person_ids"][-1] == candidate


def test_native_http_same_plan_is_merged_without_blocking_worker_followers(
    native_chain, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    from time import monotonic, sleep

    from relationship_query.runtime.relation_cache import RelationCache
    from relationship_query.services.query_plan import supplied_plan

    service = native_chain.app.state.query_service
    monkeypatch.setattr(service.graph, "cache", RelationCache("http-shared", max_bytes=0))
    original = service.select_page
    started, release, lock = Event(), Event(), Lock()
    cold = []

    def selected(request, reference):
        if supplied_plan(service.plan_key(request, reference)) is None:
            with lock:
                cold.append(1)
            started.set()
            assert release.wait(3)
        return original(request, reference)

    monkeypatch.setattr(service, "select_page", selected)
    filters = {"max_hops": 4, "relation_type": "same_company", "page_size": 2}
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = [
            executor.submit(call, native_chain, "/persons/p:expert:1/relations/search", filters)
        ]
        try:
            assert started.wait(2)
            tasks += [
                executor.submit(call, native_chain, "/persons/p:expert:1/relations/search", filters)
                for _ in range(3)
            ]
            deadline = monotonic() + 2
            while native_chain.app.state.admission.snapshot()["followers"] != 3:
                assert monotonic() < deadline
                sleep(0.005)
        finally:
            release.set()
        results = [task.result(timeout=5) for task in tasks]
    assert len(cold) == 1
    assert all(result == results[0] for result in results)
    assert native_chain.app.state.admission.snapshot()["followers"] == 0
    assert service.repository.engine.pool.checkedout() == 0


def test_native_cached_empty_page_still_verifies_graph_version(native_chain, monkeypatch):
    from relationship_query.runtime.relation_cache import RelationCache
    from relationship_query.services.query import QueryError

    graph = native_chain.app.state.query_service.graph
    monkeypatch.setattr(graph, "cache", RelationCache("empty-page"))
    filters = {
        "max_hops": 4,
        "relation_type": "same_company",
        "relation_organization_ids": ["company:5"],
    }
    assert call(native_chain, "/persons/p:expert:1/relations/search", filters)["items"] == []

    def changed(_budget):
        raise QueryError("GRAPH_VERSION_MISMATCH", "test-only", 409)

    with monkeypatch.context() as patch:
        patch.setattr(graph.client, "check_version", changed)
        response = native_chain.post("/api/v1/persons/p:expert:1/relations/search", json=filters)
        assert response.status_code == 409 and response.json()["code"] == "GRAPH_VERSION_MISMATCH"
    assert call(native_chain, "/persons/p:expert:1/relations/search", filters)["items"] == []


def test_native_topology_calculation_does_not_hold_sql_connection(native_chain, monkeypatch):
    from relationship_query.infrastructure.uuid_graph import MaterializedReader
    from relationship_query.runtime.relation_cache import RelationCache

    query = native_chain.app.state.query_service
    monkeypatch.setattr(query.graph, "cache", RelationCache("sql-lease", max_bytes=0))
    original = MaterializedReader._shortest_connections
    calls = []

    def checked(reader, *args):
        assert reader.sql is None
        assert query.repository.engine.pool.checkedout() == 0
        calls.append(1)
        return original(reader, *args)

    monkeypatch.setattr(MaterializedReader, "_shortest_connections", checked)
    result = call(native_chain, "/persons/p:expert:1/relations/search", {"max_hops": 4})
    assert result["items"] and calls == [1]


def test_native_warm_plan_keeps_live_reference_check_without_duplicate_precheck(
    native_chain, monkeypatch
):
    from relationship_query.runtime.relation_cache import RelationCache
    from relationship_query.services.query import QueryError

    service = native_chain.app.state.query_service
    monkeypatch.setattr(service.graph, "cache", RelationCache("warm-reference-check"))
    filters = {"max_hops": 4, "relation_type": "same_company", "page_size": 2}
    reference = "p:expert:1"
    calls = []
    original = service.require_person

    def checked(identity):
        calls.append(identity)
        return original(identity)

    monkeypatch.setattr(service, "require_person", checked)
    first = call(native_chain, f"/persons/{reference}/relations/search", filters)
    assert calls == [reference, reference], "冷计划及其展示分别校验"
    calls.clear()
    assert call(native_chain, f"/persons/{reference}/relations/search", filters) == first
    assert calls == [reference], "热计划仍实时校验，但不再提前重复读取"

    def removed(identity):
        raise QueryError("PERSON_NOT_FOUND", "test-only invalidated reference", 404)

    monkeypatch.setattr(service, "require_person", removed)
    response = native_chain.post(f"/api/v1/persons/{reference}/relations/search", json=filters)
    assert response.status_code == 404 and response.json()["code"] == "PERSON_NOT_FOUND"


@pytest.mark.parametrize("concurrency", [4, 8])
def test_native_warm_parallel_assembly_with_simulated_slow_display_io(
    native_chain, monkeypatch, concurrency
):
    from concurrent.futures import ThreadPoolExecutor
    from time import sleep

    from relationship_query.runtime.relation_cache import RelationCache

    service = native_chain.app.state.query_service
    monkeypatch.setattr(service.graph, "cache", RelationCache("slow-display-io"))
    endpoint = "/persons/p:expert:1/relations/search"
    filters = {"max_hops": 4, "relation_type": "same_company", "page_size": 2}
    expected = call(native_chain, endpoint, filters)
    original = service.repository.persons

    def delayed(ids):
        # 真实图与SQL结果不替换，仅模拟超过旧300ms队列等待的展示I/O。
        sleep(0.35)
        return original(ids)

    monkeypatch.setattr(service.repository, "persons", delayed)
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as workers:
        futures = [
            workers.submit(call, native_chain, endpoint, filters) for _ in range(concurrency)
        ]
        results = [future.result(timeout=5) for future in futures]
    assert results == [expected] * concurrency
    assert all(value == 0 for value in native_chain.app.state.admission.snapshot().values())
    assert service.repository.engine.pool.checkedout() == 0
    native_chain.app.state.multihop_observations.append(
        {
            "case": "simulated_350ms_display_io",
            "concurrency": concurrency,
            "success": len(results),
            "complete_response_matched": True,
            "elapsed_ms": round((perf_counter() - started) * 1000, 2),
            "resources_drained": True,
        }
    )
