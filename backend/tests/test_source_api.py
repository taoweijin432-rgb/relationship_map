"""新来源端到端验证；期望来自人工控制经历，不从查询结果生成。"""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.contracts import PathRequest, RelationScope
from relationship_query.infrastructure.graph_relation_queries import (
    SOURCE_SLOT_MODEL,
    _pair,
    candidate_query,
    evidence_query,
)
from relationship_query.infrastructure.source_graph_model import (
    SourceManifest,
    normalize_slot_proof,
)
from relationship_query.infrastructure.sql_paths import SQLPathReader
from relationship_query.services.query import QueryError
from tests.reference_oracle import expected_people, scoped_proofs
from tests.test_paths import _expected_paths, _signatures


def test_source_graph_queries_use_new_ids_and_explicit_edge_types():
    request = PathRequest(
        reference_id="p:expert:1", candidate_id="p:resume:8", intermediate_source="resume"
    )
    statement = candidate_query(request, 202611, model=SOURCE_SLOT_MODEL)
    assert "p|p:expert:1" not in statement
    assert "[x:worked_at|studied_at]" in statement
    assert 'STARTS WITH "p:resume:"' in statement
    assert "RETURN DISTINCT" in statement and "LIMIT 129" in statement
    proof = evidence_query(request, 202611, [("p:expert:1", "p:resume:8")], SOURCE_SLOT_MODEL)
    assert "rank(x) AS left_rank" in proof and "toString(e.entity.id)" in proof
    assert ".start_date" in proof and ".start_month" not in proof
    window = _pair(
        RelationScope(
            relation_type="same_company_overlap",
            relation_start_month=202101,
            relation_end_month=202112,
            min_overlap_months=12,
            relation_organization_ids=["301"],
        ),
        202611,
        "true",
        "true",
        model=SOURCE_SLOT_MODEL,
    )
    assert 'toString(e.entity.id) IN ["301"]' in window and "months >= 12" in window


def slot_proof():
    def props(rank, system, table):
        return dict(
            fact_id=f"slot:{rank}",
            kind="employment",
            active=True,
            start_date=202001,
            end_date=202212,
            is_current=False,
            role_id=316,
            source_system=system,
            source_record_id=f"{table}:1",
            source_table=table,
            source_field_id=1,
            source_field="company_name",
        )

    return dict(
        left_rank=1001,
        right_rank=1003,
        left_person="p:expert:1",
        right_person="p:resume:2",
        left_fact="slot:1001",
        right_fact="slot:1003",
        left_properties=props(1001, "expert", "experts_work_experience"),
        right_properties=props(1003, "resume", "resume_work_experience"),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("left_rank", 1002),
        ("left_rank", 2**63),
        ("left_rank", -1),
        ("left_person", "p:resume:1"),
        ("left_fact", "slot:bad"),
    ],
)
def test_rank_and_source_proof_mismatches_rejected(field, value):
    row = slot_proof()
    row[field] = value
    with pytest.raises(ValueError):
        normalize_slot_proof(row)


def test_source_proof_normalization_preserves_unknowns_and_location():
    row = slot_proof()
    row["left_properties"]["start_date"] = None
    normalized = normalize_slot_proof(row)
    assert normalized["left_properties"]["start_month"] is None
    assert normalized["left_properties"]["source_record_id"] == "experts_work_experience:1"
    assert normalized["left_properties"]["role_id"] == "316"
    row["left_properties"]["source_field"] = "position_title"
    with pytest.raises(ValueError):
        normalize_slot_proof(row)


def test_old_experimental_manifest_is_not_api_manifest():
    with pytest.raises(ValueError):
        SourceManifest.model_validate(
            dict(
                format="source-slot-lab-v2",
                space="relationship_lab_three_test",
                source_digest="a" * 64,
            )
        )


@pytest.mark.parametrize(
    "old_config",
    [
        {"mysql_url": "mysql+pymysql://root@127.0.0.1/relationship_lab_test"},
        {"graph_manifest": Path("old-manifest.json")},
        {"path": Path("old.sqlite")},
    ],
)
def test_source_and_old_config_cannot_mix(old_config, monkeypatch):
    for name in ("RELATIONSHIP_SOURCE_API_MYSQL_URL", "RELATIONSHIP_SOURCE_API_MANIFEST"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="不能混用"):
        with TestClient(create_app(source_manifest=Path("not-read.json"), **old_config)):
            pass


def test_source_url_without_manifest_cannot_fall_back(monkeypatch):
    monkeypatch.delenv("RELATIONSHIP_SOURCE_API_MANIFEST", raising=False)
    with pytest.raises(ValueError, match="不能回退"):
        with TestClient(
            create_app(source_mysql_url="mysql+pymysql://root@127.0.0.1/relationship_lab_test")
        ):
            pass


@pytest.mark.parametrize("command", ["init", "reset"])
def test_source_cli_cannot_reset_default_demo(command, tmp_path, monkeypatch):
    from relationship_query.cli import main

    target = tmp_path / "untouched.sqlite"
    monkeypatch.setenv("RELATIONSHIP_SOURCE_API_MANIFEST", "new-manifest.json")
    monkeypatch.delenv("RELATIONSHIP_MYSQL_URL", raising=False)
    monkeypatch.setenv("RELATIONSHIP_DATABASE", str(target))
    monkeypatch.setattr("sys.argv", ["relationship-query", command])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2 and not target.exists()


LIVE = pytest.mark.skipif(
    os.environ.get("RELATIONSHIP_SOURCE_API_TEST") != "1",
    reason="显式启用冻结原表／三表与本机图端到端验收",
)


def raw_reference():
    """独立展开冻结的原表样例；不调用生产适配、月份或关系计算函数。"""
    file = (
        Path(__file__).resolve().parents[2]
        / "data/projection-source-trial/run-v4/source-snapshot.json"
    )
    source = json.loads(file.read_text())
    people = [
        dict(id=f"p:{system}:{row['id']}", sources=[system], active=not row["deleted_at"])
        for system, table in (("expert", "experts"), ("resume", "resume"))
        for row in source[table]
    ]
    slots = source["Relationship_Graph_edge_mapping"]
    facts = []
    for slot in slots:
        if slot["edge_type"] not in {"worked_at", "studied_at"} or slot["deleted_at"]:
            continue
        raw = next(r for r in source[slot["source_table"]] if r["id"] == slot["source_field_id"])
        role = next(
            (
                r["entity_id"]
                for r in slots
                if r["source_system"] == slot["source_system"]
                and r["source_table"] == slot["source_table"]
                and r["source_field_id"] == raw["id"]
                and r["source_field"] == "position_title"
                and not r["deleted_at"]
            ),
            None,
        )

        def month(value):
            return int(value[:4]) * 100 + int(value[5:7]) if value else None

        facts.append(
            dict(
                id=f"slot:{slot['id']}",
                person_id=f"p:{slot['source_system']}:{raw[slot['source_system'] + '_id']}",
                type="employment" if slot["edge_type"] == "worked_at" else "education",
                entity_id=str(slot["entity_id"]),
                role_id=str(role) if role else None,
                start_month=month(raw["start_date"]),
                end_month=month(raw["end_date"]),
                is_current=raw.get("is_employed") == 1,
                active=not raw["deleted_at"],
            )
        )
    return dict(people=people, facts=facts, reference_month=202611)


@pytest.fixture
def source_client():
    manifest = Path(os.environ["RELATIONSHIP_SOURCE_API_MANIFEST"])
    with TestClient(
        create_app(
            source_manifest=manifest,
            source_mysql_url=os.environ["RELATIONSHIP_SOURCE_API_MYSQL_URL"],
        )
    ) as client:
        yield client


@LIVE
def test_actual_raw_tables_without_demo_model(source_client):
    client = source_client
    meta = client.get("/api/v1/meta").json()
    assert meta["data_version"].startswith("source-slots-v2-") and meta["data_mode"] == "mock"
    assert meta["storage"] == "mysql-source-slots"
    assert meta["person_count"] == 63 and meta["fact_count"] == 119
    facts = client.get("/api/v1/persons/p:expert:1/facts").json()["items"]
    assert [f["fact"]["source_record_id"] for f in facts if f["fact"]["type"] == "employment"] == [
        "experts_work_experience:1",
        "experts_work_experience:19",
    ]
    assert all(f["fact"]["id"].startswith("slot:") for f in facts)
    engine = client.app.state.query_service.repository.engine
    with engine.connect() as connection:
        tables = connection.exec_driver_sql("SHOW TABLES").scalars().all()
        assert len(tables) == 11 and not any(t.startswith("demo_") for t in tables)
        assert connection.exec_driver_sql("SELECT @@SESSION.transaction_read_only").scalar() == 1


@LIVE
@pytest.mark.parametrize(
    "kind,include,exclude",
    [
        (
            "same_company_overlap",
            {"p:resume:2", "p:resume:7", "p:resume:31"},
            {"p:resume:3", "p:resume:4"},
        ),
        ("same_company", {"p:resume:2", "p:resume:3", "p:resume:4", "p:resume:7"}, set()),
        ("same_school", {"p:resume:2"}, set()),
    ],
)
def test_raw_relation_search_pagination_and_types(source_client, kind, include, exclude):
    body = dict(relation_type=kind, page_size=2)
    found = []
    while True:
        response = source_client.post("/api/v1/persons/p:expert:1/relations/search", json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        found += [i["person"]["id"] for i in result["items"]]
        if not result["has_more"]:
            break
        body["cursor"] = result["next_cursor"]
    assert (
        found == sorted(set(found)) and include.issubset(found) and not exclude.intersection(found)
    )
    if body.get("cursor"):
        changed = source_client.post(
            "/api/v1/persons/p:expert:1/relations/search", json={**body, "source": "expert"}
        )
        assert changed.status_code == 422 and changed.json()["code"] == "INVALID_CURSOR"


@LIVE
def test_raw_same_experience_constraint_aliases_comparison_export(source_client):
    client = source_client
    # 冻结源映射 1001 指向 307，1002 指向 316；306 虽同名，不能替代 307。
    query = dict(organization_ids=["307"], role_ids=["316"], page_size=50)
    result = client.post("/api/v1/persons/search", json=query)
    assert result.status_code == 200, result.text
    payload = result.json()
    found = {i["person"]["id"] for i in payload["items"]}
    assert {"p:expert:1", "p:resume:31"}.issubset(found) and "p:resume:7" not in found
    assert all(e["id"] != "306" for e in payload["graph"]["nodes"])
    companies = client.get("/api/v1/entities/suggest?type=organization").json()["items"]
    assert len([c for c in companies if c["name"] == "模拟标准公司1"]) == 2
    comparison = client.post(
        "/api/v1/persons/compare", json=dict(reference_id="p:expert:1", candidate_id="p:resume:2")
    ).json()
    assert any(e["overlap_months"] == 24 for e in comparison["evidence"])
    exported = client.post(
        "/api/v1/exports/persons",
        json=dict(
            filters=query,
            data_version=payload["data_version"],
            expected_person_ids=[i["person"]["id"] for i in payload["items"]],
        ),
    )
    assert exported.status_code == 200, exported.text
    assert all(
        "source_record_id" in f["fact"] for i in exported.json()["items"] for f in i["facts"]
    )


@LIVE
def test_new_graph_paths_compute_without_sql_relationship_search(source_client, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("图路径不允许调用 SQL 关系或候选算法")

    for method in ("candidates", "qualify_candidates", "fact_views"):
        monkeypatch.setattr(SQLPathReader, method, forbidden)
    client = source_client
    response = client.post(
        "/api/v1/relations/paths",
        json=dict(
            reference_id="p:expert:1",
            candidate_id="p:resume:8",
            scope=dict(relation_type="same_company_overlap"),
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["query_backend"] == "nebula" and result["direct"] is None
    assert [p["intermediate"]["id"] for p in result["paths"]] == ["p:resume:7"]
    assert [
        [e["overlap_months"] for e in s["evidence"]] for s in result["paths"][0]["segments"]
    ] == [[24], [71]]
    assert result["search_complete"] and not result["truncated"]


@LIVE
@pytest.mark.parametrize(
    "scope,expected",
    [
        ({"relation_type": "same_company_overlap"}, [24]),
        (
            {
                "relation_type": "same_company_overlap",
                "relation_start_month": 202101,
                "relation_end_month": 202112,
                "min_overlap_months": 12,
            },
            [12],
        ),
        ({"relation_type": "same_company_overlap", "min_overlap_months": 25}, []),
        ({"relation_type": "same_school"}, [None]),
    ],
)
def test_new_graph_direct_scoped_evidence(source_client, scope, expected):
    response = source_client.post(
        "/api/v1/relations/paths",
        json=dict(reference_id="p:expert:1", candidate_id="p:resume:2", scope=scope),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    direct = result["direct"]
    assert ([e["overlap_months"] for e in direct["evidence"]] if direct else []) == expected


@LIVE
def test_source_graph_failure_and_version_drift_are_errors(source_client, monkeypatch):
    client = source_client
    repository = client.app.state.path_service.graph_repository

    def fail(_budget):
        raise QueryError("GRAPH_UNAVAILABLE", "专项模拟依赖故障", 503)

    monkeypatch.setattr(repository.client, "check_version", fail)
    response = client.post(
        "/api/v1/relations/paths", json=dict(reference_id="p:expert:1", candidate_id="p:resume:8")
    )
    assert response.status_code == 503 and response.json()["code"] == "GRAPH_UNAVAILABLE"
    source = client.app.state.query_service.repository
    old = source.manifest
    monkeypatch.setattr(source, "manifest", old.model_copy(update={"source_digest": "0" * 64}))
    response = client.post("/api/v1/persons/search", json={})
    assert response.status_code == 409 and response.json()["code"] == "SOURCE_VERSION_MISMATCH"


@LIVE
@pytest.mark.parametrize(
    "filters,reference",
    [
        ({}, None),
        ({"source": "expert"}, None),
        ({"source": "resume"}, None),
        ({"organization_ids": ["307"], "role_ids": ["316"]}, None),
        ({"organization_ids": ["304", "307"], "role_ids": ["316"]}, None),
        ({"organization_ids": ["306"]}, None),
        ({"school_ids": ["308"], "organization_ids": ["307"]}, None),
        ({"start_month": 202101}, None),
        ({"end_month": 202112}, None),
        ({"start_month": 202101, "end_month": 202112}, None),
        ({"relation_type": "same_company"}, "p:expert:1"),
        ({"relation_type": "same_company_overlap"}, "p:expert:1"),
        ({"relation_type": "same_school"}, "p:expert:1"),
        (
            {
                "relation_type": "same_company_overlap",
                "relation_start_month": 202101,
                "relation_end_month": 202112,
                "min_overlap_months": 12,
            },
            "p:expert:1",
        ),
    ],
)
def test_source_query_against_independent_raw_reference(source_client, filters, reference):
    url = f"/api/v1/persons/{reference}/relations/search" if reference else "/api/v1/persons/search"
    ids, cursor = [], None
    for _ in range(100):
        response = source_client.post(url, json={**filters, "cursor": cursor, "page_size": 7})
        assert response.status_code == 200, response.text
        result = response.json()
        ids.extend(i["person"]["id"] for i in result["items"])
        if not result["has_more"]:
            break
        cursor = result["next_cursor"]
    else:
        pytest.fail("分页未结束")
    assert ids == expected_people(raw_reference(), filters, reference)
    assert len(ids) == len(set(ids))


@LIVE
@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"relation_type": "same_school"},
        {"relation_type": "same_company"},
        {"relation_type": "same_company_overlap"},
        {"relation_type": "same_company", "relation_organization_ids": ["307"]},
        {
            "relation_type": "same_company_overlap",
            "relation_start_month": 202101,
            "relation_end_month": 202112,
        },
    ],
)
@pytest.mark.parametrize("source", [None, "expert", "resume"])
def test_new_graph_paths_and_evidence_against_independent_raw_reference(
    source_client, scope, source
):
    left, right = "p:expert:1", "p:resume:8"
    response = source_client.post(
        "/api/v1/relations/paths",
        json=dict(
            reference_id=left,
            candidate_id=right,
            scope=scope,
            intermediate_source=source,
            limits={"candidate_limit": 500, "path_limit": 20, "evidence_limit": 50},
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    expected = _expected_paths(raw_reference(), left, right, scope, source)
    assert result["search_complete"] and not result["truncated"]
    assert [p["intermediate"]["id"] for p in result["paths"]] == [p[0] for p in expected]
    direct = scoped_proofs(raw_reference(), left, right, scope)
    assert sorted(_signatures(result["direct"]) if result["direct"] else []) == sorted(direct)
    for path, (_, first, second) in zip(result["paths"], expected, strict=True):
        assert sorted(_signatures(path["segments"][0])) == sorted(first)
        assert sorted(_signatures(path["segments"][1])) == sorted(second)


@LIVE
def test_new_source_graph_limit_does_not_truncate_list(source_client):
    response = source_client.post(
        "/api/v1/graph/expand",
        json=dict(person_id="p:expert:1", existing_node_ids=[f"reserved:{i}" for i in range(100)]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["graph"]["truncated"] and response.json()["graph"]["nodes"] == []
    query = source_client.post(
        "/api/v1/persons/p:expert:1/relations/search", json={"page_size": 50}
    ).json()
    assert len(query["items"]) > 1


@LIVE
def test_source_graph_candidate_and_evidence_limits_are_explicit(source_client):
    limited = source_client.post(
        "/api/v1/relations/paths",
        json=dict(
            reference_id="p:expert:1",
            candidate_id="p:resume:8",
            scope={"relation_type": "same_company"},
            limits={"candidate_limit": 1},
        ),
    ).json()
    assert limited["truncated"] and not limited["search_complete"]
    assert "candidate_limit" in limited["truncation_reasons"]
    evidence = source_client.post(
        "/api/v1/relations/paths",
        json=dict(
            reference_id="p:expert:1",
            candidate_id="p:resume:3",
            scope={"relation_type": "same_company"},
            limits={"evidence_limit": 1},
        ),
    ).json()
    assert evidence["direct"]["evidence_truncated"] and len(evidence["direct"]["evidence"]) == 1


@LIVE
def test_source_graph_marker_mismatch_returns_conflict(source_client, monkeypatch):
    graph = source_client.app.state.path_service.graph_repository.client
    monkeypatch.setattr(
        graph,
        "execute",
        lambda *_args: [{"meta": {"status": "building", "digest": graph.manifest.source_digest}}],
    )
    response = source_client.post(
        "/api/v1/relations/paths", json=dict(reference_id="p:expert:1", candidate_id="p:resume:8")
    )
    assert response.status_code == 409 and response.json()["code"] == "GRAPH_VERSION_MISMATCH"
