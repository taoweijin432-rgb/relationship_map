import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from relationship_query.contracts import ExpandRequest, SearchRequest
from relationship_query.domain.models import Dataset
from relationship_query.infrastructure.sqlite import SQLiteRepository, load_dataset, open_engine
from relationship_query.services.query import QueryService
from tests.differential_data import differential_dataset
from tests.reference_oracle import (
    Proof,
    expected_people,
    expected_proofs,
    scoped_proofs,
    select_proofs,
)

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DATA = ROOT / "resources/examples/logical-dataset.json"
CASES = json.loads((Path(__file__).parent / "fixtures/query-cases.json").read_text())


@pytest.fixture
def golden_service(tmp_path: Path) -> Iterator[QueryService]:
    engine = open_engine(tmp_path / "golden.sqlite")
    load_dataset(engine, Dataset.model_validate_json(GOLDEN_DATA.read_text()))
    yield QueryService(SQLiteRepository(engine))
    engine.dispose()


def all_items(
    service: QueryService, filters: dict[str, Any], reference: str | None, page_size: int
) -> list[Any]:
    cursor, items = None, []
    for _ in range(1000):
        response = service.search(
            SearchRequest.model_validate({**filters, "page_size": page_size, "cursor": cursor}),
            reference,
        )
        items.extend(response.items)
        if not response.has_more:
            assert response.next_cursor is None
            return items
        assert response.next_cursor and response.next_cursor != cursor
        cursor = response.next_cursor
    pytest.fail("分页未结束")


@pytest.mark.parametrize("case", CASES["searches"], ids=lambda case: case["name"])
@pytest.mark.parametrize("page_size", [1, 3, 7, 20])
def test_hand_checked_people(
    golden_service: QueryService, case: dict[str, Any], page_size: int
) -> None:
    items = all_items(golden_service, case["filters"], case.get("reference"), page_size)
    actual = [item.person.id for item in items]
    assert actual == case["expected"]
    assert len(actual) == len(set(actual))
    raw = json.loads(GOLDEN_DATA.read_text())
    assert expected_people(raw, case["filters"], case.get("reference")) == case["expected"]
    if case.get("reference"):
        for item in items:
            valid_ids = {
                ev.id for ev in golden_service.evidence(case["reference"], item.person.id).items
            }
            assert all(summary.evidence_id in valid_ids for summary in item.relations)


def actual_proofs(service: QueryService, reference: str, candidate: str) -> list[Proof]:
    return [
        (
            ev.relation_type,
            ev.entity.id,
            ev.reference.fact.id,
            ev.candidate.fact.id,
            (ev.overlap_start, ev.overlap_end, ev.overlap_months)
            if ev.overlap_months is not None
            else None,
        )
        for ev in service.evidence(reference, candidate).items
    ]


@pytest.mark.parametrize("case", CASES["evidence"], ids=lambda case: case["candidate"])
def test_hand_checked_evidence(golden_service: QueryService, case: dict[str, Any]) -> None:
    expected = [
        (kind, entity, a, b, tuple(window) if window is not None else None)
        for kind, entity, a, b, window in case["expected"]
    ]
    actual = actual_proofs(golden_service, "p:01", case["candidate"])
    assert sorted(actual) == sorted(expected)
    raw = json.loads(GOLDEN_DATA.read_text())
    assert sorted(expected_proofs(raw, "p:01", case["candidate"])) == sorted(expected)
    facts = {fact["id"]: fact for fact in raw["facts"]}
    for evidence in golden_service.evidence("p:01", case["candidate"]).items:
        for view in (evidence.reference, evidence.candidate):
            assert view.fact.source_record_id == facts[view.fact.id]["source_record_id"]


def test_graph_truncation_does_not_limit_people_or_evidence(golden_service: QueryService) -> None:
    response = golden_service.expand(
        ExpandRequest(person_id="p:01", existing_node_ids=[f"reserved:{i}" for i in range(99)])
    )
    assert response.graph.truncated
    assert len(response.graph.nodes) <= 1
    assert [i.person.id for i in all_items(golden_service, {}, "p:01", 2)] == [
        "p:02",
        "p:03",
        "p:04",
        "p:05",
        "p:06",
        "p:08",
        "p:11",
        "p:12",
        "p:13",
    ]
    assert len(golden_service.evidence("p:01", "p:08").items) == 4


def test_independent_500_person_differential(tmp_path: Path) -> None:
    raw = differential_dataset()
    engine = open_engine(tmp_path / "differential.sqlite")
    load_dataset(engine, Dataset.model_validate(raw))
    service = QueryService(SQLiteRepository(engine))
    entity_names = {entity["id"]: entity["name"] for entity in raw["entities"]}
    requests = [
        {},
        {
            "organization_ids": ["org:0", "org:1"],
            "role_ids": ["role:0", "role:1"],
            "school_ids": ["school:1", "school:2"],
        },
        {"organization_ids": ["org:0", "org:2", "org:0"], "organization_id": "org:1"},
        {"school_ids": ["school:0", "school:5"], "start_month": 202001},
        {"organization_ids": [], "school_ids": [], "role_ids": []},
        {"source": "expert"},
        {"source": "resume"},
        *[{"organization_id": f"org:{i}"} for i in range(12)],
        *[{"school_id": f"school:{i}"} for i in range(6)],
        *[
            {"organization_id": "org:0", "role_id": f"role:{i}", "source": "resume"}
            for i in range(5)
        ],
        {"start_month": 202001},
        {"end_month": 201812},
        {"start_month": 202012, "end_month": 202101},
        {"organization_id": "org:0", "school_id": "school:1", "end_month": 202301},
    ]
    try:
        for filters in requests:
            actual = [i.person.id for i in all_items(service, filters, None, 17)]
            assert actual == expected_people(raw, filters), filters
            assert len(actual) == len(set(actual))
        for reference in ("d:0000", "d:0001", "d:0002"):
            for kind in (None, "same_company", "same_company_overlap", "same_school"):
                filters = {"relation_type": kind}
                items = all_items(service, filters, reference, 17)
                assert [i.person.id for i in items] == expected_people(raw, filters, reference)
                for item in items:
                    proofs = select_proofs(expected_proofs(raw, reference, item.person.id), kind)
                    expected_summary = {(p[0], entity_names[p[1]]) for p in proofs}
                    assert {(r.type, r.entity_name) for r in item.relations} == expected_summary
            # 所有有效人物对的证据均与独立月份集合算法比较，包括没有关系的人物。
            for person in raw["people"]:
                if person["active"]:
                    assert sorted(actual_proofs(service, reference, person["id"])) == sorted(
                        expected_proofs(raw, reference, person["id"])
                    )
    finally:
        engine.dispose()


def test_scoped_500_person_differential(tmp_path: Path) -> None:
    raw = differential_dataset()
    engine = open_engine(tmp_path / "scoped-differential.sqlite")
    load_dataset(engine, Dataset.model_validate(raw))
    service = QueryService(SQLiteRepository(engine))
    scopes = [
        {"relation_type": "same_company", "relation_organization_ids": ["org:0", "org:2"]},
        {"relation_type": "same_company_overlap", "min_overlap_months": 24},
        {
            "relation_type": "same_company_overlap",
            "relation_start_month": 202012,
            "relation_end_month": 202101,
            "min_overlap_months": 2,
        },
        {
            "relation_type": "same_company_overlap",
            "relation_start_month": 202201,
            "min_overlap_months": 6,
            "source": "expert",
        },
        {
            "relation_type": "same_company_overlap",
            "relation_end_month": 201812,
            "min_overlap_months": 1,
        },
        {
            "relation_type": "same_company_overlap",
            "relation_organization_ids": ["org:0"],
            "organization_ids": ["org:1"],
            "min_overlap_months": 12,
        },
    ]
    try:
        for reference in ("d:0000", "d:0001", "d:0002"):
            for filters in scopes:
                items = all_items(service, filters, reference, 7)
                assert [item.person.id for item in items] == expected_people(
                    raw, filters, reference
                )
                for item in items:
                    expected = scoped_proofs(raw, reference, item.person.id, filters)
                    evidence = service.evidence(
                        reference, item.person.id, SearchRequest.model_validate(filters)
                    ).items
                    actual = [
                        (
                            ev.relation_type,
                            ev.entity.id,
                            ev.reference.fact.id,
                            ev.candidate.fact.id,
                            (ev.overlap_start, ev.overlap_end, ev.overlap_months)
                            if ev.overlap_months
                            else None,
                        )
                        for ev in evidence
                    ]
                    assert sorted(actual) == sorted(expected)
                    assert {summary.evidence_id for summary in item.relations} <= {
                        ev.id for ev in evidence
                    }
    finally:
        engine.dispose()
