"""合并详情保留独立API语义，并验证实时人物与完整事实的复用边界。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import event, update

from relationship_query.contracts import PersonDetailsRequest
from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.fixtures import make_dataset
from relationship_query.infrastructure.sql_paths import SQLPathReader
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.infrastructure.sqlite import load_dataset, open_engine
from relationship_query.runtime.fact_indexes import fact_indexes
from relationship_query.services.query import QueryError

from .test_live_people import live as live
from .test_real_query import real_release as real_release


@pytest.mark.parametrize("reference", [None, "p:000001", "p:000002"])
def test_details_match_existing_facts_and_evidence(client, reference):
    candidate = "p:000002"
    facts = client.get(f"/api/v1/persons/{candidate}/facts").json()
    body = {"reference_id": reference, "filters": {"relation_type": "same_company"}}
    response = client.post(f"/api/v1/persons/{candidate}/details", json=body)
    assert response.status_code == 200, response.text
    details = response.json()
    assert details["person"] == facts["person"] and details["facts"] == facts["items"]
    assert details["data_version"] == facts["data_version"]
    if reference and reference != candidate:
        proof = client.post(
            "/api/v1/relations/evidence/search",
            json={"reference_id": reference, "candidate_id": candidate, "filters": body["filters"]},
        ).json()
        assert details["reference"] == proof["reference"]
        assert details["evidence"] == proof["items"]
        assert details["connection"] == proof["connection"]
    else:
        assert details["reference"] is None and not details["evidence"]


def test_details_not_found_and_invalid_filters(client):
    assert client.post("/api/v1/persons/missing/details", json={}).status_code == 404
    response = client.post(
        "/api/v1/persons/p:000002/details",
        json={"reference_id": "p:000001", "filters": {"organization_ids": ["missing"]}},
    )
    assert response.status_code == 422 and response.json()["code"] == "INVALID_ENTITY"


def test_complete_person_facts_reuse_across_repo_and_path_reader(tmp_path):
    engine = open_engine(tmp_path / "facts.sqlite")
    data = make_dataset()
    load_dataset(engine, data)
    repo = SQLRepository(engine)
    calls = []
    event.listen(engine, "before_cursor_execute", lambda *args: calls.append(1))
    try:
        with fact_indexes():
            original = repo.fact_views(["p:000001", "p:000002"])
            calls.clear()
            assert repo.fact_views(["p:000002"]) == [
                view for view in original if view.fact.person_id == "p:000002"
            ]
            with engine.connect() as connection:
                reader = SQLPathReader(connection, PathBudget(5000, 5000), data.reference_month)
                assert reader.fact_views_by_ids([view.fact.id for view in original]) == original
            assert not calls
        assert repo.fact_views(["p:000002"])
        assert len(calls) == 2
    finally:
        engine.dispose()


def test_live_details_deduplicate_reads_and_reverify_without_cross_request_cache(live, monkeypatch):
    live.repository.graph = SimpleNamespace(connected=lambda *args: True)
    calls = []
    original = live.people._read

    def fetch(ids):
        calls.append(tuple(ids))
        return original(ids)

    monkeypatch.setattr(live.people, "_read", fetch)
    request = PersonDetailsRequest(reference_id="p:expert:1")
    result = live.service.details("p:resume:1", request)
    assert result.person.name == "在线人物resume"
    # 首次参考／候选各一次，装配中重读复用；末次真实批量检查两人。
    assert calls == [("p:expert:1",), ("p:resume:1",), ("p:expert:1", "p:resume:1")]
    with live.engine.begin() as connection:
        connection.execute(update(live.schema.tables["resume"]).values(name="新名字"))
    assert live.service.details("p:resume:1", request).person.name == "新名字"


@pytest.mark.parametrize("change", [dict(name="查询中改名"), dict(deleted_at="2026-11-16")])
def test_live_change_during_detail_assembly_is_rejected(live, monkeypatch, change):
    original = live.repository.fact_views

    def facts(ids):
        result = original(ids)
        with live.engine.begin() as connection:
            connection.execute(update(live.schema.tables["experts"]).values(**change))
        return result

    monkeypatch.setattr(live.repository, "fact_views", facts)
    with pytest.raises(QueryError) as changed:
        live.service.details("p:expert:1", PersonDetailsRequest())
    assert changed.value.code == "PERSON_SOURCE_CHANGED"
