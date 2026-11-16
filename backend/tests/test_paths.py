import json
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from relationship_query.app import create_app
from relationship_query.contracts import PathRequest
from relationship_query.domain.models import Dataset
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.sqlite import SQLiteRepository, load_dataset, open_engine
from relationship_query.infrastructure.sqlite_paths import SQLitePathRepository
from relationship_query.services.paths import PathService
from relationship_query.services.query import QueryService
from tests.differential_data import differential_dataset
from tests.reference_oracle import scoped_proofs

SAMPLE = Path(__file__).resolve().parents[2] / "resources/examples/logical-dataset.json"
ENDPOINT = "/api/v1/relations/paths"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    path = tmp_path / "paths.sqlite"
    engine = open_engine(path)
    load_dataset(engine, Dataset.model_validate_json(SAMPLE.read_text()))
    engine.dispose()
    with TestClient(create_app(path)) as instance:
        yield instance


def search(client: TestClient, candidate: str = "p:07", **options: object) -> dict:
    response = client.post(
        ENDPOINT, json={"reference_id": "p:01", "candidate_id": candidate, **options}
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "scope,source,expected",
    [
        ({"relation_type": "same_company_overlap"}, None, ["p:06"]),
        ({"relation_type": "same_company"}, None, ["p:06"]),
        ({"relation_type": "same_school"}, None, []),
        ({}, None, ["p:03", "p:06", "p:08", "p:13"]),
        ({}, "expert", ["p:08"]),
        ({"relation_type": "same_company_overlap"}, "expert", []),
        ({"relation_type": "same_company_overlap", "min_overlap_months": 12}, None, ["p:06"]),
        (
            {
                "relation_type": "same_company_overlap",
                "relation_start_month": 202101,
                "relation_end_month": 202112,
            },
            None,
            [],
        ),
        ({"relation_type": "same_company", "relation_organization_ids": ["org:a"]}, None, []),
    ],
)
def test_hand_checked_paths_and_sources(
    client: TestClient, scope: dict, source: str | None, expected: list[str]
) -> None:
    data = search(client, scope=scope, intermediate_source=source)
    assert data["direct"] is None and data["direct_checked"]
    assert [path["intermediate"]["id"] for path in data["paths"]] == expected
    assert data["search_complete"] and not data["truncated"]
    assert data["status"] == ("found" if expected else "not_found")
    assert data["reference"]["name"] == data["candidate"]["name"]
    assert data["reference"]["id"] != data["candidate"]["id"]
    assert data["data_mode"] == "mock" and data["data_version"] == "handoff-example-v1"
    for path in data["paths"]:
        assert len(path["segments"]) == 2
        assert path["segments"][0]["to_person"]["id"] == path["intermediate"]["id"]
        assert path["segments"][1]["from_person"]["id"] == path["intermediate"]["id"]
        for segment in path["segments"]:
            assert segment["evidence"] and not segment["evidence_truncated"]
            assert all(
                proof["reference"]["fact"]["active"] and proof["candidate"]["fact"]["active"]
                for proof in segment["evidence"]
            )


def test_different_segment_dates_do_not_require_three_people_coincide(client: TestClient) -> None:
    data = search(client, scope={"relation_type": "same_company_overlap"})
    first, second = data["paths"][0]["segments"]
    assert (first["evidence"][0]["overlap_start"], first["evidence"][0]["overlap_end"]) == (
        202001,
        202112,
    )
    assert (second["evidence"][0]["overlap_start"], second["evidence"][0]["overlap_end"]) == (
        202201,
        202212,
    )
    assert first["evidence"][0]["candidate"]["fact"]["source_record_id"] == "demo-resume-work-06a"
    assert second["evidence"][0]["reference"]["fact"]["source_record_id"] == "demo-resume-work-06b"


def test_direct_and_indirect_coexist_and_duplicate_employment_is_not_duplicate_path(
    client: TestClient,
) -> None:
    data = search(client, "p:02", scope={"relation_type": "same_company_overlap"})
    assert data["direct"]["evidence"][0]["overlap_months"] == 24
    assert [p["intermediate"]["id"] for p in data["paths"]] == ["p:05", "p:06", "p:08", "p:12"]
    duplicate = next(path for path in data["paths"] if path["intermediate"]["id"] == "p:08")
    assert len(duplicate["segments"][0]["evidence"]) == 2
    assert len({path["id"] for path in data["paths"]}) == len(data["paths"])
    reverse = client.post(
        ENDPOINT,
        json={
            "reference_id": "p:07",
            "candidate_id": "p:01",
            "scope": {"relation_type": "same_company_overlap"},
        },
    ).json()
    assert [p["intermediate"]["id"] for p in reverse["paths"]] == ["p:06"]
    assert reverse["paths"][0]["segments"][0]["evidence"][0]["overlap_months"] == 12


@pytest.mark.parametrize(
    "options",
    [
        {"candidate_id": "p:01"},
        {"candidate_id": "missing"},
        {"candidate_id": "p:09"},
        {"reference_id": "missing"},
        {"scope": {"relation_type": "same_school", "min_overlap_months": 1}},
        {"scope": {"relation_type": "same_company", "relation_organization_ids": ["school:x"]}},
        {"scope": {"relation_type": "same_company", "relation_organization_ids": ["missing"]}},
        {"scope": {"relation_type": "same_company_overlap", "relation_start_month": 202113}},
        {"scope": {"role_ids": ["role:director"]}},
        {"limits": {"candidate_limit": 501}},
        {"limits": {"path_limit": 21}},
        {"limits": {"time_budget_ms": 3001}},
        {"limits": {"evidence_limit": 0}},
        {"intermediate_source": "unknown"},
        {"max_depth": 3},
    ],
)
def test_invalid_or_unknown_input(client: TestClient, options: dict) -> None:
    response = client.post(
        ENDPOINT, json={"reference_id": "p:01", "candidate_id": "p:07", **options}
    )
    assert response.status_code == (
        404
        if options.get("candidate_id") in {"missing", "p:09"}
        or options.get("reference_id") == "missing"
        else 422
    )
    assert response.json()["data_mode"] == "mock"


def test_candidate_path_fact_and_evidence_limits_are_distinct(client: TestClient) -> None:
    data = search(
        client, scope={"relation_type": "same_company_overlap"}, limits={"candidate_limit": 1}
    )
    assert data["status"] == "limited" and data["paths"] == []
    assert data["direct_checked"] and not data["search_complete"]
    assert data["truncation_reasons"] == ["candidate_limit"]
    assert data["stats"]["candidates_examined"] == 1
    limited = search(client, scope={}, limits={"path_limit": 1})
    assert [p["intermediate"]["id"] for p in limited["paths"]] == ["p:03"]
    assert limited["truncation_reasons"] == ["path_limit"] and limited["status"] == "found"
    facts = search(client, limits={"fact_limit": 1})
    assert facts["status"] == "limited" and not facts["direct_checked"]
    assert facts["truncation_reasons"] == ["fact_limit"]
    assert facts["stats"]["fact_rows_loaded"] <= 1
    proofs = search(
        client,
        "p:08",
        scope={"relation_type": "same_company_overlap"},
        limits={"evidence_limit": 1},
    )
    assert proofs["direct"]["evidence_truncated"] and len(proofs["direct"]["evidence"]) == 1
    assert proofs["search_complete"] and proofs["truncation_reasons"] == ["evidence_limit"]
    exact_limit = search(
        client, scope={"relation_type": "same_company_overlap"}, limits={"path_limit": 1}
    )
    assert len(exact_limit["paths"]) == 1 and exact_limit["search_complete"]


def test_time_and_pair_budgets_do_not_report_no_connection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from itertools import count

    from relationship_query.services import paths as paths_module

    clock = count(0, 10)
    client.app.state.path_service.clock = lambda: next(clock)
    timed = search(client)
    assert timed["status"] == "limited" and timed["truncation_reasons"] == ["time_limit"]
    assert not timed["direct_checked"]
    from time import monotonic

    client.app.state.path_service.clock = monotonic
    monkeypatch.setattr(
        paths_module,
        "PathBudget",
        lambda time_ms, fact_limit, clock: PathBudget(
            time_ms, fact_limit, clock=clock, pair_limit=1
        ),
    )
    pair = search(client)
    assert pair["status"] == "limited" and pair["truncation_reasons"] == ["pair_limit"]
    assert pair["stats"]["evidence_pairs_examined"] <= 1


def test_sql_interrupt_cleanup_and_storage_failure_are_not_empty_results(
    client: TestClient,
) -> None:
    queries = client.app.state.query_service
    repository = SQLitePathRepository(
        queries.repository.engine, queries.repository.version, queries.repository.reference_month
    )
    budget = PathBudget(3000, 100, sql_limit=1000)
    with pytest.raises(PathBudgetExceeded, match="sql_limit"):
        with repository.session(budget) as reader:
            reader.connection.exec_driver_sql(
                "WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL "
                "SELECT x+1 FROM n WHERE x<1000000) SELECT sum(x) FROM n"
            )
    with queries.repository.engine.connect() as connection:
        assert connection.scalar(select(1)) == 1
    with pytest.raises(OperationalError):
        with repository.session(PathBudget(3000, 100)) as reader:
            reader.connection.exec_driver_sql("SELECT * FROM nonexistent_path_test_table")
    assert search(client)["status"] == "found"


def _expected_paths(
    raw: dict, left: str, right: str, scope: dict, source: str | None
) -> list[tuple]:
    result = []
    for person in sorted(raw["people"], key=lambda p: p["id"]):
        middle = person["id"]
        if (
            not person.get("active", True)
            or middle in {left, right}
            or source
            and source not in person["sources"]
        ):
            continue
        first, second = (
            scoped_proofs(raw, left, middle, scope),
            scoped_proofs(raw, middle, right, scope),
        )
        if first and second:
            result.append((middle, first, second))
    return result


def _signatures(segment: dict) -> list[tuple]:
    return [
        (
            proof["relation_type"],
            proof["entity"]["id"],
            proof["reference"]["fact"]["id"],
            proof["candidate"]["fact"]["id"],
            (proof["overlap_start"], proof["overlap_end"], proof["overlap_months"])
            if proof["overlap_months"]
            else None,
        )
        for proof in segment["evidence"]
    ]


def test_independent_500_person_paths_and_read_only_input(tmp_path: Path) -> None:
    raw = differential_dataset()
    path = tmp_path / "differential-paths.sqlite"
    engine = open_engine(path)
    load_dataset(engine, Dataset.model_validate(raw))
    query = QueryService(SQLiteRepository(engine))
    service = PathService(
        SQLitePathRepository(engine, query.repository.version, query.repository.reference_month),
        query,
    )
    before = sha256(path.read_bytes()).hexdigest()
    try:
        for left, right in (("d:0000", "d:0001"), ("d:0000", "d:0002"), ("d:0001", "d:0002")):
            for scope in (
                {},
                {"relation_type": "same_school"},
                {"relation_type": "same_company"},
                {"relation_type": "same_company_overlap"},
                {
                    "relation_type": "same_company_overlap",
                    "relation_start_month": 202012,
                    "relation_end_month": 202101,
                    "min_overlap_months": 2,
                },
            ):
                for source in (None, "expert"):
                    request = PathRequest.model_validate(
                        {
                            "reference_id": left,
                            "candidate_id": right,
                            "scope": scope,
                            "intermediate_source": source,
                            "limits": {
                                "candidate_limit": 500,
                                "path_limit": 20,
                                "fact_limit": 5000,
                                "evidence_limit": 100,
                                "time_budget_ms": 3000,
                            },
                        }
                    )
                    actual = service.search(request).model_dump()
                    expected = _expected_paths(raw, left, right, scope, source)
                    assert [p["intermediate"]["id"] for p in actual["paths"]] == [
                        p[0] for p in expected[:20]
                    ]
                    assert actual["search_complete"] == (len(expected) <= 20)
                    direct = scoped_proofs(raw, left, right, scope)
                    direct_signatures = _signatures(actual["direct"]) if actual["direct"] else []
                    assert sorted(direct_signatures) == sorted(direct)
                    for returned, (_, first, second) in zip(actual["paths"], expected):
                        assert sorted(_signatures(returned["segments"][0])) == sorted(first)
                        assert sorted(_signatures(returned["segments"][1])) == sorted(second)
        assert sha256(path.read_bytes()).hexdigest() == before
    finally:
        engine.dispose()


def test_school_unknown_dates_and_inactive_middle_people(client: TestClient) -> None:
    data = search(client, "p:02", scope={"relation_type": "same_school"})
    assert data["direct"]["evidence"][0]["overlap_months"] is None
    assert "p:04" in [path["intermediate"]["id"] for path in data["paths"]]
    assert "p:09" not in [path["intermediate"]["id"] for path in data["paths"]]
    for path in data["paths"]:
        assert all(
            proof["relation_type"] == "same_school" and proof["overlap_months"] is None
            for segment in path["segments"]
            for proof in segment["evidence"]
        )


def test_three_hop_chain_does_not_count_as_one_middle_person(tmp_path: Path) -> None:
    raw = json.loads(SAMPLE.read_text())
    raw["entities"].append({"id": "org:c", "name": "虚构第三公司", "type": "organization"})
    raw["facts"] = [
        {
            "id": f"chain:{index}",
            "person_id": person,
            "type": "employment",
            "entity_id": company,
            "start_month": 202001,
            "end_month": 202012,
            "source_system": source,
            "source_record_id": f"fictional-chain-{index}",
        }
        for index, (person, company, source) in enumerate(
            [
                ("p:01", "org:a", "expert"),
                ("p:06", "org:a", "resume"),
                ("p:06", "org:b", "resume"),
                ("p:08", "org:b", "expert"),
                ("p:08", "org:c", "expert"),
                ("p:07", "org:c", "resume"),
            ]
        )
    ]
    path = tmp_path / "three-hop.sqlite"
    engine = open_engine(path)
    load_dataset(engine, Dataset.model_validate(raw))
    engine.dispose()
    with TestClient(create_app(path)) as client:
        result = search(client, scope={"relation_type": "same_company_overlap"})
        assert result["status"] == "not_found" and result["search_complete"]
        assert result["paths"] == [] and result["direct"] is None


def test_api_storage_failure_returns_service_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    @contextmanager
    def broken_session(_budget: PathBudget) -> Iterator[None]:
        raise OperationalError("read path", {}, RuntimeError("test storage failure"))
        yield

    monkeypatch.setattr(client.app.state.path_service.repository, "session", broken_session)
    response = client.post(ENDPOINT, json={"reference_id": "p:01", "candidate_id": "p:07"})
    assert response.status_code == 503
    assert response.json()["code"] == "STORAGE_UNAVAILABLE"
