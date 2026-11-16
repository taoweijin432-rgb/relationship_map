import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.domain.models import Dataset
from relationship_query.infrastructure.sqlite import load_dataset, open_engine
from tests.reference_oracle import expected_people, expected_proofs

SAMPLE = Path(__file__).resolve().parents[2] / "resources/examples/logical-dataset.json"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "comparison.sqlite"
    engine = open_engine(path)
    load_dataset(engine, Dataset.model_validate_json(SAMPLE.read_text()))
    engine.dispose()
    with TestClient(create_app(path)) as instance:
        yield instance


@pytest.mark.parametrize(
    "filters,expected",
    [
        (
            {"organization_ids": ["org:a", "org:b"], "role_ids": ["role:director"]},
            ["p:01", "p:06", "p:08"],
        ),
        ({"organization_ids": ["org:a"], "role_ids": ["role:director"]}, ["p:01", "p:08"]),
        (
            {
                "school_ids": ["school:x", "school:z"],
                "role_ids": ["role:director", "role:researcher"],
            },
            ["p:01", "p:11", "p:12"],
        ),
        (
            {
                "organization_ids": ["org:a"],
                "school_ids": ["school:x", "school:y"],
                "role_ids": ["role:engineer", "role:researcher"],
            },
            ["p:02", "p:04", "p:06", "p:11"],
        ),
    ],
)
def test_multi_select_or_within_and_between_categories(
    client: TestClient, filters: dict, expected: list[str]
) -> None:
    response = client.post("/api/v1/persons/search", json=filters)
    assert response.status_code == 200
    assert [i["person"]["id"] for i in response.json()["items"]] == expected
    assert expected_people(json.loads(SAMPLE.read_text()), filters) == expected


def test_legacy_scalar_and_equivalent_arrays_share_cursor_context(client: TestClient) -> None:
    first = client.post(
        "/api/v1/persons/search",
        json={"organization_id": "org:a", "organization_ids": ["org:b", "org:a"], "page_size": 2},
    ).json()
    next_page = client.post(
        "/api/v1/persons/search",
        json={
            "organization_ids": ["org:a", "org:b"],
            "page_size": 2,
            "cursor": first["next_cursor"],
        },
    )
    assert next_page.status_code == 200
    assert [i["person"]["id"] for i in next_page.json()["items"]] == ["p:03", "p:04"]
    changed = client.post(
        "/api/v1/persons/search",
        json={"organization_ids": ["org:a"], "cursor": first["next_cursor"]},
    )
    assert changed.status_code == 422 and changed.json()["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize(
    "filters",
    [
        {"organization_ids": ["org:a", "missing"]},
        {"school_ids": ["org:a"]},
        {"role_ids": [""]},
        {"organization_ids": ["org:a"] * 51},
    ],
)
def test_every_selection_is_validated(client: TestClient, filters: dict) -> None:
    assert client.post("/api/v1/persons/search", json=filters).status_code == 422


@pytest.mark.parametrize(
    "candidate", ["p:02", "p:03", "p:04", "p:05", "p:07", "p:08", "p:10", "p:11", "p:12"]
)
def test_comparison_evidence_agrees_with_independent_oracle(
    client: TestClient, candidate: str
) -> None:
    response = client.post(
        "/api/v1/persons/compare", json={"reference_id": "p:01", "candidate_id": candidate}
    )
    assert response.status_code == 200
    result = response.json()
    expected = expected_proofs(json.loads(SAMPLE.read_text()), "p:01", candidate)
    actual = [
        (
            ev["relation_type"],
            ev["entity"]["id"],
            ev["reference"]["fact"]["id"],
            ev["candidate"]["fact"]["id"],
            (ev["overlap_start"], ev["overlap_end"], ev["overlap_months"])
            if ev["overlap_months"] is not None
            else None,
        )
        for ev in result["evidence"]
    ]
    assert sorted(actual) == sorted(expected)
    assert all(v["fact"]["active"] for v in result["reference_facts"] + result["candidate_facts"])
    assert result["data_mode"] == "mock" and result["reference_month"] == 202611


def test_swap_unknown_and_same_person_comparison(client: TestClient) -> None:
    forward = client.post(
        "/api/v1/persons/compare", json={"reference_id": "p:01", "candidate_id": "p:02"}
    ).json()
    reverse = client.post(
        "/api/v1/persons/compare", json={"reference_id": "p:02", "candidate_id": "p:01"}
    ).json()
    assert reverse["reference"]["id"] == forward["candidate"]["id"]
    assert reverse["candidate_facts"] == forward["reference_facts"]
    assert {ev["overlap_months"] for ev in reverse["evidence"]} == {
        ev["overlap_months"] for ev in forward["evidence"]
    }
    assert (
        client.post(
            "/api/v1/persons/compare", json={"reference_id": "p:01", "candidate_id": "p:01"}
        ).status_code
        == 422
    )
    for person in ("missing", "p:09"):
        assert (
            client.post(
                "/api/v1/persons/compare", json={"reference_id": "p:01", "candidate_id": person}
            ).status_code
            == 404
        )
