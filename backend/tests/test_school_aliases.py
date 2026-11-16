"""学校曾用名从冻结输入进入发布读模型及候选API的回归。"""

import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from relationship_query.api.routes import router
from relationship_query.contracts import SearchRequest
from relationship_query.infrastructure.numeric_read_model import query_schema
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.services.query import QueryService
from relationship_query.update.models import UpdateError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def school_capture(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "school_alias_build", ROOT / "scripts/build_real_graph.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tables = json.loads((ROOT / "resources/examples/update-baseline-v1.json").read_text())["tables"]
    del tables["mock.graph_expert_name_mapping"]
    entities, people = {}, {}
    for logical, physical in (module.ENTITY_TABLES | module.PERSON_TABLES).items():
        records = tables[f"mock.{physical}"]
        if logical in ("company", "school", "major"):
            for row in records:
                row.update(uuid=f"test-{logical}-{row['id']}", verification_status="已核验")
        else:
            for row in records:
                if logical.startswith("person_"):
                    row.update(city="", job_name="")
        (entities if logical in module.ENTITY_TABLES else people)[physical] = records
    original = entities["graph_school_entity"][0]
    original.update(id=41, standard_name="广东医科大学", former_names='["广东医学院"]')
    entities["graph_school_entity"].append(
        {
            **original,
            "id": 73,
            "uuid": "test-school-73",
            "standard_name": "浙江科技大学",
            "school_code": "school-73",
            "former_names": ["浙江科技学院"],
        }
    )
    for row in entities["graph_edge_mapping"]:
        if row["edge_type"] == "studied_at":
            row["standard_entity_id"] = 41
    capture = tmp_path / "capture"
    capture.mkdir()
    return module, capture, entities, people


@contextmanager
def prepared_repository(school_capture, output):
    module, capture, entities, people = school_capture
    (capture / "entity-source.json").write_text(
        json.dumps({"metadata": {"database": "mapping_test"}, "tables": entities})
    )
    (capture / "person-source.json").write_text(
        json.dumps(
            {"metadata": {"database": "people_test"}, "tables": people, "scope": "test-only"}
        )
    )
    metadata = module.prepare(capture, output, 202611)
    engine = create_engine(f"sqlite:///{output / 'source.sqlite'}")
    _, tables = query_schema()
    try:
        yield SQLRepository(engine, tables=tables), metadata
    finally:
        engine.dispose()


def test_former_and_standard_names_return_same_entity_and_filtered_people(school_capture, tmp_path):
    with prepared_repository(school_capture, tmp_path / "release") as (repository, _):
        app = FastAPI()
        app.include_router(router)
        app.state.query_service = QueryService(repository)
        with TestClient(app) as client:
            for former, standard, identity in (
                ("广东医学院", "广东医科大学", "school:41"),
                ("浙江科技学院", "浙江科技大学", "school:73"),
            ):
                responses = [
                    client.get("/api/v1/entities/suggest", params={"type": "school", "q": q})
                    for q in (former, standard)
                ]
                assert all(response.status_code == 200 for response in responses)
                old, current = [response.json()["items"] for response in responses]
                assert old == current
                assert [(entity["id"], entity["name"]) for entity in old] == [(identity, standard)]
                assert former in old[0]["aliases"]
                results = [
                    client.post("/api/v1/persons/search", json={"school_ids": [items[0]["id"]]})
                    for items in (old, current)
                ]
                assert all(response.status_code == 200 for response in results)
                assert results[0].json() == results[1].json()
        assert repository.search_ids(SearchRequest(school_ids=["school:41"]), None, None)


def test_aliases_trim_deduplicate_and_keep_shared_name_per_entity(school_capture, tmp_path):
    schools = school_capture[2]["graph_school_entity"]
    schools[0]["former_names"] = [
        " 广东医学院 ",
        "广东医学院",
        "",
        "  ",
        "广东医科大学",
        "共同旧称",
    ]
    schools[1]["former_names"] = ["共同旧称", "旧_%校"]
    with prepared_repository(school_capture, tmp_path / "release") as (repository, _):
        assert repository.entity("school:41").aliases == ["共同旧称", "广东医学院"]
        assert {item.id for item in repository.suggest_entities("school", "共同旧称", 50)} == {
            "school:41",
            "school:73",
        }
        assert [item.id for item in repository.suggest_entities("school", "旧_%", 50)] == [
            "school:73"
        ]
        with repository.engine.connect() as connection:
            rows = connection.execute(select(repository.tables.aliases)).all()
        assert len(rows) == len(set(rows)) == 4


@pytest.mark.parametrize("empty", [None, [], "[]", "null"])
def test_empty_former_names_and_legacy_capture_remain_usable(school_capture, tmp_path, empty):
    schools = school_capture[2]["graph_school_entity"]
    schools[0]["former_names"] = empty
    schools[1]["former_names"] = empty
    with prepared_repository(school_capture, tmp_path / "empty") as (repository, _):
        assert repository.entity("school:41").aliases == []
    for row in schools:
        del row["former_names"]
    with prepared_repository(school_capture, tmp_path / "legacy") as (repository, _):
        assert repository.entity("school:41").aliases == []
        assert repository.suggest_entities("school", "广东医科大学", 50)


@pytest.mark.parametrize(
    "value", ["{broken", '{"old":"广东医学院"}', '"广东医学院"', [123], [None], True]
)
def test_invalid_alias_payload_rejects_candidate(school_capture, tmp_path, value):
    school_capture[2]["graph_school_entity"][0]["former_names"] = value
    with pytest.raises(UpdateError) as error:
        with prepared_repository(school_capture, tmp_path / "release"):
            pass
    assert error.value.code == "INVALID_ALIASES"


def test_alias_update_changes_version_and_new_release_replaces_old_aliases(
    school_capture, tmp_path
):
    with prepared_repository(school_capture, tmp_path / "old") as (repository, before):
        assert repository.suggest_entities("school", "广东医学院", 50)
    school_capture[2]["graph_school_entity"][0]["former_names"] = '["更新旧称"]'
    with prepared_repository(school_capture, tmp_path / "new") as (repository, after):
        assert after["version"] != before["version"]
        assert repository.suggest_entities("school", "广东医学院", 50) == []
        assert repository.suggest_entities("school", "更新旧称", 50)[0].id == "school:41"
    school_capture[2]["graph_school_entity"][0]["former_names"] = None
    with prepared_repository(school_capture, tmp_path / "removed") as (repository, removed):
        assert removed["version"] != after["version"]
        assert repository.suggest_entities("school", "更新旧称", 50) == []


@pytest.mark.parametrize("status,deleted_at", [("已合并", None), ("已核验", "2026-11-01")])
def test_unpublished_school_aliases_are_excluded(school_capture, tmp_path, status, deleted_at):
    school_capture[2]["graph_school_entity"][1].update(
        verification_status=status, deleted_at=deleted_at
    )
    with prepared_repository(school_capture, tmp_path / "release") as (repository, _):
        assert repository.suggest_entities("school", "浙江科技学院", 50) == []
        assert repository.entity("school:73") is None
