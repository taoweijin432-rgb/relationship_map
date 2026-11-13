from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from relationship_query.infrastructure.fixtures import make_dataset
from relationship_query.infrastructure.sqlite import (
    SQLiteRepository,
    facts,
    load_dataset,
    open_engine,
)


def result_ids(client: TestClient, body: dict, reference: str | None = None) -> list[str]:
    endpoint = (
        f"/api/v1/persons/{reference}/relations/search" if reference else "/api/v1/persons/search"
    )
    response = client.post(endpoint, json={"page_size": 50, **body})
    assert response.status_code == 200, response.text
    return [item["person"]["id"] for item in response.json()["items"]]


def test_company_and_role_must_share_one_fact(client: TestClient) -> None:
    ids = result_ids(client, {"organization_id": "org:0", "role_id": "role:0"})
    assert "p:000001" in ids
    assert "p:000007" not in ids  # 此人在 org:1 才担任 role:0。
    assert "p:000007" in result_ids(client, {"organization_id": "org:0", "role_id": "role:2"})


def test_overlap_unknown_time_and_historical_company(client: TestClient) -> None:
    overlap_ids = result_ids(client, {"relation_type": "same_company_overlap"}, "p:000001")
    company_ids = result_ids(client, {"relation_type": "same_company"}, "p:000001")
    assert "p:000002" in overlap_ids and "p:000005" in overlap_ids
    assert "p:000003" not in overlap_ids and "p:000004" not in overlap_ids
    assert {"p:000003", "p:000004"} <= set(company_ids)
    assert "p:000001" not in company_ids


def test_school_does_not_invent_dates(client: TestClient) -> None:
    response = client.get(
        "/api/v1/relations/evidence",
        params={"reference_id": "p:000001", "candidate_id": "p:000004"},
    ).json()
    school = next(ev for ev in response["items"] if ev["relation_type"] == "same_school")
    assert school["overlap_months"] is None
    assert "不据此推断同期" in school["explanation"]


def test_overlap_evidence_months_and_source_trace(client: TestClient) -> None:
    response = client.get(
        "/api/v1/relations/evidence",
        params={"reference_id": "p:000001", "candidate_id": "p:000002"},
    ).json()
    match = next(ev for ev in response["items"] if ev["relation_type"] == "same_company_overlap")
    assert (match["overlap_start"], match["overlap_end"], match["overlap_months"]) == (
        202101,
        202212,
        24,
    )
    assert match["reference"]["fact"]["source_record_id"] == "demo-work-1"
    current = client.get(
        "/api/v1/relations/evidence",
        params={"reference_id": "p:000001", "candidate_id": "p:000005"},
    ).json()
    assert any(ev["overlap_end"] == 202611 for ev in current["items"])


def test_inactive_records_and_duplicates(client: TestClient) -> None:
    ids = result_ids(client, {"organization_id": "org:0"})
    assert "p:000006" not in ids and "p:000011" not in ids
    assert ids.count("p:000001") == 1
    assert result_ids(client, {"source": "expert"}).count("p:000013") == 1
    assert result_ids(client, {"source": "resume"}).count("p:000013") == 1


def test_cursor_complete_stable_and_bound_to_filters(client: TestClient) -> None:
    expected = result_ids(client, {})
    collected, cursor = [], None
    while True:
        response = client.post(
            "/api/v1/persons/search", json={"page_size": 7, "cursor": cursor}
        ).json()
        collected.extend(item["person"]["id"] for item in response["items"])
        cursor = response["next_cursor"]
        if not response["has_more"]:
            break
    # result_ids 请求最多 50 人，完整页要另取剩余候选。
    assert collected[:50] == expected
    assert len(collected) == len(set(collected)) == 59
    first = client.post("/api/v1/persons/search", json={"page_size": 5}).json()
    changed = client.post(
        "/api/v1/persons/search", json={"cursor": first["next_cursor"], "source": "expert"}
    )
    assert changed.status_code == 422 and changed.json()["code"] == "INVALID_CURSOR"
    client.app.state.query_service.repository.version = "mock-v2"
    changed_version = client.post("/api/v1/persons/search", json={"cursor": first["next_cursor"]})
    assert changed_version.status_code == 422


def test_invalid_input_and_missing_person(client: TestClient) -> None:
    for payload in (
        {"start_month": 202613},
        {"start_month": 202501, "end_month": 202401},
        {"page_size": 51},
        {"role_id": "org:0"},
        {"relation_type": "same_school"},
    ):
        assert client.post("/api/v1/persons/search", json=payload).status_code == 422
    assert client.post("/api/v1/persons/search", json={"cursor": "not-base64"}).status_code == 422
    for person_id in ("missing", "p:000011"):
        response = client.get(f"/api/v1/persons/{person_id}/facts")
        assert response.status_code == 404 and response.json()["data_mode"] == "mock"


def test_same_name_and_alias_suggestions(client: TestClient) -> None:
    people = client.get("/api/v1/persons/suggest", params={"q": "林知远"}).json()["items"]
    assert len(people) == 2 and people[0]["id"] != people[1]["id"]
    assert client.get("/api/v1/persons/suggest", params={"q": "p:000001"}).json()["items"] == []
    assert client.get("/api/v1/persons/p:000001/facts").status_code == 200
    entities = client.get(
        "/api/v1/entities/suggest", params={"type": "organization", "q": "星澜科技有限"}
    ).json()["items"]
    assert len(entities) == 1 and entities[0]["id"] == "org:0"


def test_graph_budget_and_reference_integrity(client: TestClient) -> None:
    known = [f"existing:{i}" for i in range(98)]
    response = client.post(
        "/api/v1/graph/expand",
        json={"person_id": "p:000001", "existing_node_ids": known, "existing_edge_ids": []},
    )
    assert response.status_code == 200
    graph = response.json()["graph"]
    present = set(known) | {node["id"] for node in graph["nodes"]}
    assert len(present) <= 100 and len(graph["edges"]) <= 200
    assert graph["truncated"] and graph["truncation_reason"]
    assert all(edge["source"] in present and edge["target"] in present for edge in graph["edges"])
    full = client.post("/api/v1/persons/search", json={"page_size": 50}).json()
    assert len(full["items"]) == 50
    assert all(edge["fact_id"] for edge in full["graph"]["edges"])


def test_metadata_is_actual_and_query_is_read_only(client: TestClient) -> None:
    meta = client.get("/api/v1/meta").json()
    assert meta["person_count"] == 59 and meta["data_mode"] == "mock"
    assert meta["expert_count"] + meta["resume_count"] > meta["person_count"]
    assert client.get("/api/v1/health").status_code == 200


def test_init_preserves_data_and_reset_is_explicit(tmp_path: Path) -> None:
    engine = open_engine(tmp_path / "demo.sqlite")
    dataset = make_dataset()
    assert load_dataset(engine, dataset)
    with engine.begin() as connection:
        connection.execute(update(facts).where(facts.c.id == "f:000001:work").values(active=False))
    assert not load_dataset(engine, dataset)
    with engine.connect() as connection:
        assert (
            connection.scalar(select(facts.c.active).where(facts.c.id == "f:000001:work")) is False
        )
    assert load_dataset(engine, dataset, reset=True)
    assert SQLiteRepository(engine).version == "mock-v1"
    engine.dispose()
