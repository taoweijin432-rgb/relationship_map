import json
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.domain.models import Dataset
from relationship_query.infrastructure.sqlite import load_dataset, open_engine
from tests.reference_oracle import scoped_proofs

SAMPLE = Path(__file__).resolve().parents[2] / "resources/examples/logical-dataset.json"


def test_export_does_not_modify_database_or_input(client: TestClient) -> None:
    path = Path(client.app.state.query_service.repository.engine.url.database)
    before_db = sha256(path.read_bytes()).hexdigest()
    before_input = sha256(SAMPLE.read_bytes()).hexdigest()
    page = client.post("/api/v1/persons/search", json={"page_size": 2}).json()
    response = client.post(
        "/api/v1/exports/persons",
        json={
            "filters": page["applied_filters"],
            "data_version": page["data_version"],
            "expected_person_ids": [item["person"]["id"] for item in page["items"]],
        },
    )
    assert response.status_code == 200
    assert sha256(path.read_bytes()).hexdigest() == before_db
    assert sha256(SAMPLE.read_bytes()).hexdigest() == before_input


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "scope.sqlite"
    engine = open_engine(path)
    load_dataset(engine, Dataset.model_validate_json(SAMPLE.read_text()))
    engine.dispose()
    with TestClient(create_app(path)) as instance:
        yield instance


def test_topic_metadata_alias_and_existing_paginated_members(client: TestClient) -> None:
    result = client.get("/api/v1/entities/org:a").json()
    assert result["entity"]["aliases"] == ["星澜科技有限公司", "星澜"]
    assert result["data_mode"] == "mock"
    assert client.get("/api/v1/entities/missing").status_code == 404
    assert client.get("/api/v1/entities/school:x").json()["entity"]["type"] == "school"
    first = client.post(
        "/api/v1/persons/search", json={"organization_ids": ["org:a"], "page_size": 2}
    ).json()
    assert [item["person"]["id"] for item in first["items"]] == ["p:01", "p:02"]
    assert first["has_more"] and first["applied_filters"]["organization_ids"] == ["org:a"]


@pytest.mark.parametrize(
    "filters",
    [
        {"relation_type": "same_school", "min_overlap_months": 1},
        {"relation_type": "same_company", "relation_start_month": 202001},
        {
            "relation_type": "same_company_overlap",
            "relation_start_month": 202201,
            "relation_end_month": 202112,
        },
        {"relation_type": "same_company_overlap", "relation_end_month": 202113},
        {"relation_type": "same_company_overlap", "min_overlap_months": 0},
        {"relation_type": "same_company_overlap", "min_overlap_months": 2413},
        {"relation_type": "same_company", "relation_organization_ids": ["school:x"]},
        {"relation_type": "same_company", "relation_organization_ids": ["missing"]},
        {"relation_organization_ids": ["org:a"]},
    ],
)
def test_invalid_relation_scope(client: TestClient, filters: dict) -> None:
    assert client.post("/api/v1/persons/p:01/relations/search", json=filters).status_code == 422
    assert client.post("/api/v1/persons/search", json=filters).status_code == 422


def test_scoped_evidence_clips_window_and_respects_candidate_background(client: TestClient) -> None:
    filters = {
        "relation_type": "same_company_overlap",
        "relation_organization_ids": ["org:a"],
        "relation_start_month": 202101,
        "relation_end_month": 202112,
        "min_overlap_months": 12,
    }
    result = client.post(
        "/api/v1/relations/evidence/search",
        json={"reference_id": "p:01", "candidate_id": "p:02", "filters": filters},
    ).json()
    assert len(result["items"]) == 1
    proof = result["items"][0]
    assert (proof["overlap_start"], proof["overlap_end"], proof["overlap_months"]) == (
        202101,
        202112,
        12,
    )
    assert proof["reference"]["fact"]["end_month"] == 202212
    assert proof["candidate"]["fact"]["source_record_id"] == "demo-resume-work-02"
    assert scoped_proofs(json.loads(SAMPLE.read_text()), "p:01", "p:02", filters)[0][4] == (
        202101,
        202112,
        12,
    )
    excluded = client.post(
        "/api/v1/relations/evidence/search",
        json={
            "reference_id": "p:01",
            "candidate_id": "p:02",
            "filters": {**filters, "source": "expert"},
        },
    ).json()
    assert excluded["items"] == []
    unscoped = client.get(
        "/api/v1/relations/evidence", params={"reference_id": "p:01", "candidate_id": "p:02"}
    ).json()
    assert unscoped["items"][0]["overlap_months"] == 24


def test_relation_scope_cursor_graph_and_current_page_export(client: TestClient) -> None:
    filters = {
        "relation_type": "same_company_overlap",
        "relation_start_month": 202101,
        "relation_end_month": 202112,
        "min_overlap_months": 12,
        "page_size": 2,
    }
    first = client.post("/api/v1/persons/p:01/relations/search", json=filters).json()
    assert [i["person"]["id"] for i in first["items"]] == ["p:02", "p:06"]
    second = client.post(
        "/api/v1/persons/p:01/relations/search", json={**filters, "cursor": first["next_cursor"]}
    ).json()
    assert [i["person"]["id"] for i in second["items"]] == ["p:08"]
    assert not second["has_more"]
    assert {edge["fact_id"] for edge in first["graph"]["edges"]} == {"f:01a", "f:02a", "f:06a"}
    changed = client.post(
        "/api/v1/persons/p:01/relations/search",
        json={**filters, "min_overlap_months": 13, "cursor": first["next_cursor"]},
    )
    assert changed.status_code == 422 and changed.json()["code"] == "INVALID_CURSOR"
    export_body = {
        "reference_id": "p:01",
        "filters": second["applied_filters"],
        "data_version": second["data_version"],
        "expected_person_ids": ["p:08"],
    }
    data = client.post("/api/v1/exports/persons", json=export_body).json()
    assert data["scope"] == "current_page" and data["facts_scope"] == "all_active_person_facts"
    assert len(data["items"]) == 1 and len(data["items"][0]["evidence"]) == 2
    assert all(ev["overlap_months"] == 12 for ev in data["items"][0]["evidence"])
    assert all(f["fact"]["active"] for f in data["items"][0]["facts"])
    assert (
        client.post(
            "/api/v1/exports/persons", json={**export_body, "data_version": "old"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/exports/persons", json={**export_body, "expected_person_ids": ["p:02"]}
        ).status_code
        == 409
    )


def test_entity_export_contains_fact_provenance_and_no_inferred_relationship(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/persons/search", json={"school_ids": ["school:x"], "page_size": 2}
    ).json()
    data = client.post(
        "/api/v1/exports/persons",
        json={
            "reference_id": None,
            "filters": response["applied_filters"],
            "data_version": response["data_version"],
            "expected_person_ids": ["p:01", "p:02"],
        },
    ).json()
    assert data["has_more"] and data["data_mode"] == "mock"
    assert all(not item["evidence"] for item in data["items"])
    assert data["items"][0]["facts"][0]["fact"]["source_record_id"] == "demo-expert-work-01a"
