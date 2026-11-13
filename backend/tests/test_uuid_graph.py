"""新模型的预检与独立原表基准；原生联调必须显式选择本轮实验快照。"""

import copy
import json
import os
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.infrastructure.source_releases import read_bundle
from relationship_query.infrastructure.uuid_projection import estimate
from relationship_query.infrastructure.uuid_source import NAMES, projection_records

C = "00000000-0000-4000-8000-000000000001"
S = "00000000-0000-4000-8000-000000000002"
M = "00000000-0000-4000-8000-000000000003"


@pytest.fixture
def small_source():
    data = {name: [] for name in NAMES}
    for tag, key in (("company", C), ("school", S), ("major", M)):
        data[f"graph_{tag}_entity"] = [
            dict(id=key, standard_name="虚构实体", **{f"{tag}_code": "MOCK-001"}, is_deleted=0)
        ]
    data["experts"] = [
        dict(id=1, serial_number="e000000000000000001", name="禁止入图的虚构姓名", deleted_at=None)
    ]
    data["experts_work_experience"] = [
        dict(
            id=9,
            expert_id=1,
            start_date=datetime(2020, 1, 1),
            end_date=datetime(2021, 1, 1),
            position_title="工程师",
            is_employed=2,
            deleted_at=None,
        )
    ]
    data["experts_education_experience"] = [
        dict(
            id=8,
            expert_id=1,
            start_date=None,
            end_date=None,
            education_level="本科",
            is_regular_enrollment="原文待确认",
            deleted_at=None,
        )
    ]
    for rank, edge, table, field, key, raw_id in (
        (7001, "worked_at", "experts_work_experience", "company_name", C, 9),
        (8001, "studied_at", "experts_education_experience", "school_name", S, 8),
        (8002, "studied_major", "experts_education_experience", "major", M, 8),
    ):
        data["graph_edge_mapping"].append(
            dict(
                id=rank,
                edge_type=edge,
                source_system="expert",
                source_table=table,
                source_field=field,
                source_field_id=raw_id,
                source_person_id=1,
                standard_entity_id=key,
                deleted_at=None,
            )
        )
    return data


def test_privacy_rank_and_education_grouping(small_source):
    before = copy.deepcopy(small_source)
    nodes, edges = projection_records(small_source, 202611)
    person = next(n for n in nodes if n["type"] == "person")
    assert person["properties"] == dict(source_system="expert", serial_number="e000000000000000001")
    assert "禁止入图的虚构姓名" not in json.dumps([nodes, edges], ensure_ascii=False)
    assert [e["rank"] for e in edges] == [7001, 8001, 8002]
    assert edges[1]["properties"] == edges[2]["properties"]
    assert edges[1]["properties"]["experience_key"] == "expert:experts_education_experience:8"
    assert edges[1]["properties"]["is_regular_enrollment"] == "原文待确认"
    assert small_source == before
    assert estimate(edges) == 0


@pytest.mark.parametrize(
    "mutation", ["uuid_collision", "rank", "owner", "kind", "day", "current", "serial"]
)
def test_precheck_rejects_invalid_source(small_source, mutation):
    data = small_source
    if mutation == "uuid_collision":
        data["graph_school_entity"][0]["id"] = C
    elif mutation == "rank":
        data["graph_edge_mapping"][1]["id"] = 7001
    elif mutation == "owner":
        data["graph_edge_mapping"][0]["source_person_id"] = 2
    elif mutation == "kind":
        data["graph_edge_mapping"][0]["standard_entity_id"] = S
    elif mutation == "day":
        data["experts_work_experience"][0].update(
            start_date=datetime(2021, 1, 20), end_date=datetime(2021, 1, 2)
        )
    elif mutation == "current":
        data["experts_work_experience"][0]["is_employed"] = 1
    else:
        data["experts"][0]["serial_number"] = ""
    with pytest.raises(ValueError):
        projection_records(data, 202611)


@pytest.mark.parametrize(
    "table", ["graph_company_entity", "experts", "experts_work_experience", "graph_edge_mapping"]
)
def test_inactive_records_do_not_project(small_source, table):
    row = small_source[table][0]
    row["is_deleted" if table.endswith("_entity") else "deleted_at"] = 1
    _, edges = projection_records(small_source, 202611)
    assert not any(e["type"] == "worked_at" for e in edges)


def independent_oracle(data, month):
    """只解释原始行和明确映射；不调用生产转换、关系或日期函数。"""
    facts = []
    for m in data["graph_edge_mapping"]:
        prefix = "experts" if m["source_system"] == "expert" else "resume"
        person = next(p for p in data[prefix] if p["id"] == m["source_person_id"])
        raw = next(r for r in data[m["source_table"]] if r["id"] == m["source_field_id"])
        if m["deleted_at"] or person["deleted_at"] or raw["deleted_at"]:
            continue

        def ym(value):
            return int(value[:4]) * 100 + int(value[5:7]) if value else None

        start, end = ym(raw["start_date"]), ym(raw["end_date"])
        if m["edge_type"] == "worked_at" and raw["is_employed"] == 1:
            end = month
        facts.append(
            dict(
                person=f"p:{m['source_system']}:{m['source_person_id']}",
                entity="e:" + m["standard_entity_id"],
                edge=m["edge_type"],
                rank=m["id"],
                start=start,
                end=end,
            )
        )
    expected = set()
    for a, b in combinations(facts, 2):
        if a["person"] == b["person"] or a["entity"] != b["entity"] or a["edge"] != b["edge"]:
            continue
        left, right = sorted((a, b), key=lambda f: f["person"])
        kind = {
            "worked_at": "same_company",
            "studied_at": "same_school",
            "studied_major": "same_major",
        }[a["edge"]]
        key = (kind, left["person"], right["person"], a["entity"], left["rank"], right["rank"])
        expected.add((*key, None, None))
        if kind == "same_company" and all(
            f[k] is not None for f in (a, b) for k in ("start", "end")
        ):
            lo, hi = max(a["start"], b["start"]), min(a["end"], b["end"])
            if lo <= hi:
                expected.add(("company_overlap", *key[1:], lo, hi))
    return expected


@pytest.fixture(scope="module")
def native():
    selected = os.environ.get("RELATIONSHIP_UUID_TEST_DIR")
    if not selected:
        pytest.skip("需显式选择本轮 UUID 本地快照")
    directory = Path(selected)
    bundle = read_bundle(directory)
    from relationship_query.infrastructure.uuid_verification import verify_bundle_graph

    verify_bundle_graph(directory)
    data = json.loads((directory / "source-snapshot.json").read_text())
    edges = json.loads((directory / "graph-edges.json").read_text())
    expected = independent_oracle(data, bundle.manifest.reference_month)
    from relationship_query.infrastructure.uuid_projection import graph_digest

    nodes = json.loads((directory / "graph-nodes.json").read_text())
    assert graph_digest(nodes, edges) == bundle.manifest.graph_digest
    with TestClient(
        create_app(source_manifest=directory / "manifest.json", source_mysql_url=bundle.mysql_url)
    ) as client:
        yield client, expected, edges, data


def test_native_all_materialized_edges_match_independent_raw_oracle(native):
    _, expected, edges, _ = native
    actual = set()
    ranks = defaultdict(list)
    for e in edges:
        if e["type"] in ("worked_at", "studied_at", "studied_major"):
            continue
        p = e["properties"]
        actual.add(
            (
                e["type"],
                e["source"],
                e["target"],
                p["entity_vid"],
                p["left_fact_rank"],
                p["right_fact_rank"],
                p.get("overlap_start_month"),
                p.get("overlap_end_month"),
            )
        )
        ranks[(e["type"], e["source"], e["target"])].append(e["rank"])
    assert actual == expected
    assert all(sorted(values) == list(range(1, len(values) + 1)) for values in ranks.values())


@pytest.mark.parametrize(
    "kind", [None, "same_company", "same_company_overlap", "same_school", "same_major"]
)
def test_native_pagination_is_graph_driven(native, kind, monkeypatch):
    client, expected, _, _ = native

    def forbidden(*args, **kwargs):
        raise AssertionError("SQL/Python must not calculate relationships in UUID mode")

    monkeypatch.setattr("relationship_query.services.query.build_evidence", forbidden)
    monkeypatch.setattr(
        "relationship_query.infrastructure.sql_repository.SQLRepository._relation_condition",
        forbidden,
    )
    selected = (
        {"company_overlap"}
        if kind == "same_company_overlap"
        else ({kind} if kind else {"same_company", "company_overlap", "same_school", "same_major"})
    )
    people = {
        b if a == "p:expert:1" else a
        for k, a, b, *_ in expected
        if k in selected and "p:expert:1" in (a, b)
    }
    found, cursor = [], None
    while True:
        r = client.post(
            "/api/v1/persons/p:expert:1/relations/search",
            json=dict(relation_type=kind, page_size=7, cursor=cursor),
        )
        assert r.status_code == 200, r.text
        page = r.json()
        found.extend(i["person"]["id"] for i in page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert found == sorted(people)


def test_native_evidence_orientation_scope_and_manual_boundaries(native):
    client, _, _, _ = native
    for left, right in (("p:expert:1", "p:resume:2"), ("p:resume:2", "p:expert:1")):
        r = client.post(
            "/api/v1/relations/evidence/search",
            json=dict(
                reference_id=left,
                candidate_id=right,
                filters=dict(
                    relation_type="same_company_overlap",
                    relation_start_month=202112,
                    relation_end_month=202201,
                    min_overlap_months=2,
                ),
            ),
        )
        assert r.status_code == 200, r.text
        ev = r.json()["items"]
        assert len(ev) == 1
        assert (ev[0]["overlap_start"], ev[0]["overlap_end"], ev[0]["overlap_months"]) == (
            202112,
            202201,
            2,
        )
        assert ev[0]["reference"]["fact"]["person_id"] == left
        assert ev[0]["candidate"]["fact"]["person_id"] == right
    for other in ("p:resume:3", "p:resume:4"):
        r = client.post(
            "/api/v1/relations/evidence/search",
            json=dict(
                reference_id="p:expert:1",
                candidate_id=other,
                filters=dict(relation_type="same_company_overlap"),
            ),
        )
        assert r.status_code == 200
        assert r.json()["items"] == []


@pytest.mark.parametrize("kind", ["same_company_overlap", "same_school", "same_major"])
def test_native_two_edge_paths_match_oracle(native, kind, monkeypatch):
    client, expected, _, _ = native

    def forbidden(*args, **kwargs):
        raise AssertionError("SQL candidate search must not be called")

    monkeypatch.setattr(
        "relationship_query.infrastructure.sql_paths.SQLPathReader.candidates", forbidden
    )
    physical = "company_overlap" if kind == "same_company_overlap" else kind
    neighbors = defaultdict(set)
    for k, a, b, *_ in expected:
        if k == physical:
            neighbors[a].add(b)
            neighbors[b].add(a)
    wanted = sorted(
        m
        for m in neighbors["p:expert:1"] & neighbors["p:resume:2"]
        if m.startswith("p:expert:") and m not in ("p:expert:1", "p:resume:2")
    )
    r = client.post(
        "/api/v1/relations/paths",
        json=dict(
            reference_id="p:expert:1",
            candidate_id="p:resume:2",
            scope=dict(relation_type=kind),
            intermediate_source="expert",
            limits=dict(path_limit=20, time_budget_ms=3000),
        ),
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["query_backend"] == "nebula"
    assert [p["intermediate"]["id"] for p in result["paths"]] == wanted
    assert not result["truncated"], result["truncation_reasons"]


def test_native_background_filter_export_and_comparison(native, monkeypatch):
    client, _, _, data = native

    def forbidden(*args, **kwargs):
        raise AssertionError("Python relationship builder was called")

    monkeypatch.setattr("relationship_query.services.query.build_evidence", forbidden)
    company = next(
        e["id"]
        for e in data["graph_company_entity"]
        if e["standard_name"] == "模拟标准公司1" and e["company_code"] == "C000"
    )
    filters = dict(organization_ids=[company], position_titles=["技术总监"], page_size=20)
    r = client.post("/api/v1/persons/search", json=filters)
    assert r.status_code == 200, r.text
    page = r.json()
    ids = [item["person"]["id"] for item in page["items"]]
    assert "p:expert:1" in ids
    assert "p:resume:7" not in ids  # Company 1 + role in company 2 must not combine.
    r = client.post(
        "/api/v1/persons/compare", json=dict(reference_id="p:expert:1", candidate_id="p:resume:2")
    )
    assert r.status_code == 200, r.text
    assert {e["relation_type"] for e in r.json()["evidence"]} >= {
        "same_company_overlap",
        "same_school",
        "same_major",
    }
    r = client.post(
        "/api/v1/exports/persons",
        json=dict(filters=filters, data_version=page["data_version"], expected_person_ids=ids),
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/persons/p:expert:1/relations/search",
        json=dict(relation_type="same_major", page_size=2),
    )
    assert r.status_code == 200
    page = r.json()
    r = client.post(
        "/api/v1/exports/persons",
        json=dict(
            reference_id="p:expert:1",
            filters=dict(relation_type="same_major", page_size=2),
            data_version=page["data_version"],
            expected_person_ids=[i["person"]["id"] for i in page["items"]],
        ),
    )
    assert r.status_code == 200, r.text
    assert all(
        ev["relation_type"] == "same_major" for item in r.json()["items"] for ev in item["evidence"]
    )


def test_native_graph_limits_do_not_truncate_lists(native):
    client, _, _, _ = native
    r = client.post(
        "/api/v1/relations/paths",
        json=dict(
            reference_id="p:expert:1",
            candidate_id="p:resume:2",
            scope=dict(relation_type="same_major"),
            limits=dict(path_limit=1, evidence_limit=1, time_budget_ms=3000),
        ),
    )
    assert r.status_code == 200
    assert r.json()["truncated"]
    assert "path_limit" in r.json()["truncation_reasons"]
    r = client.post(
        "/api/v1/graph/expand",
        json=dict(
            person_id="p:expert:1",
            filters=dict(relation_type="same_major"),
            existing_node_ids=[f"already:{i}" for i in range(100)],
            existing_edge_ids=[],
        ),
    )
    assert r.status_code == 200, r.text
    assert r.json()["graph"]["truncated"]
    assert r.json()["has_more"]


def test_native_graph_failure_has_no_sql_fallback(native, monkeypatch):
    from relationship_query.infrastructure.graph_client import GraphDependencyError

    client, _, _, _ = native

    def unavailable(*args, **kwargs):
        raise GraphDependencyError()

    graph = client.app.state.query_service.graph
    monkeypatch.setattr(graph.client, "execute", unavailable)
    response = client.post("/api/v1/persons/p:expert:1/relations/search", json={})
    assert response.status_code == 503
    assert response.json()["code"] == "GRAPH_UNAVAILABLE"
    response = client.get("/api/v1/persons/suggest", params={"q": "e000000000000000001"})
    assert response.status_code == 200
    assert [p["id"] for p in response.json()["items"]] == ["p:expert:1"]
