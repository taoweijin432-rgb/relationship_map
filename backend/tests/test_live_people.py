"""在线人物源边界使用独立SQL库，覆盖接口装配与图读取回调。"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, update

from relationship_query.app import create_app
from relationship_query.contracts import ExportRequest, SearchRequest
from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure import live_people
from relationship_query.infrastructure.live_people import LiveRealGraphRepository, MySQLPeople
from relationship_query.infrastructure.uuid_graph import MaterializedReader
from relationship_query.services.query import QueryError, QueryService

from .test_real_query import real_release as real_release


@pytest.fixture
def live(real_release, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'online.sqlite'}")
    schema = MetaData()
    for name in ("experts", "resume"):
        table = Table(
            name,
            schema,
            Column("id", Integer, primary_key=True),
            *(
                Column(field, String)
                for field in ("name", "city", "job_name", "serial_number", "deleted_at")
            ),
        )
        schema.create_all(engine)
        with engine.begin() as connection:
            connection.execute(
                insert(table),
                [
                    dict(
                        id=1,
                        name="在线人物" + name,
                        city="杭州",
                        job_name="在线职位",
                        serial_number="LIVE-" + name,
                        deleted_at=None,
                    ),
                    dict(
                        id=999,
                        name="未发布人物",
                        city="",
                        job_name="",
                        serial_number="NEW",
                        deleted_at=None,
                    ),
                ],
            )
    people = MySQLPeople(engine)
    repository = LiveRealGraphRepository(real_release, people)
    try:
        yield SimpleNamespace(
            engine=engine,
            schema=schema,
            people=people,
            repository=repository,
            service=QueryService(repository),
        )
    finally:
        repository.engine.dispose()
        engine.dispose()


def test_online_fields_refresh_without_sqlite_mutation(live):
    person = live.repository.person("p:expert:1")
    assert person.name == "在线人物experts"
    assert person.city == "杭州" and person.headline == "在线职位"
    assert person.serial_number == "LIVE-experts"
    with live.engine.begin() as connection:
        connection.execute(
            update(live.schema.tables["experts"])
            .where(live.schema.tables["experts"].c.id == 1)
            .values(name="更新后的名字", city="成都")
        )
    assert live.repository.person("p:expert:1").name == "更新后的名字"
    assert live.repository.person("p:expert:1").city == "成都"
    live.repository.verify_snapshot()


def test_unpublished_identity_is_excluded(live):
    assert live.repository.person("p:expert:999") is None
    assert live.repository.suggest_people("未发布", 20) == []


def test_suggestions_search_current_name_and_serial(live):
    for keyword in ("在线人物", "LIVE-"):
        found = live.repository.suggest_people(keyword, 20)
        assert found and all(person.name.startswith("在线人物") for person in found)
    assert live.repository.suggest_people("模拟", 20) == []
    assert live.repository.suggest_people("p:expert:1", 20) == []
    assert live.repository.suggest_people("p:resume:1", 20) == []
    assert live.repository.suggest_people("", 20)


def test_live_deleted_people_are_hidden_and_strict_chains_fail(live):
    with live.engine.begin() as connection:
        connection.execute(update(live.schema.tables["experts"]).values(deleted_at="2026-11-12"))
    assert live.repository.person("p:expert:1") is None
    assert live.repository.suggest_people("在线", 20)[0].id == "p:resume:1"
    assert live.repository.search_ids(SearchRequest(page_size=1), None, None) == ["p:resume:1"]
    with pytest.raises(QueryError) as error:
        live.repository.persons(["p:expert:1", "p:resume:1"])
    assert error.value.code == "PERSON_SOURCE_CHANGED"
    with pytest.raises(QueryError) as error:
        live.service.facts("p:expert:1")
    assert error.value.status == 404


def test_pagination_probe_uses_one_recall_when_live_people_are_active(live, monkeypatch):
    from relationship_query.infrastructure.materialized_sql import MaterializedSQLRepository

    original = MaterializedSQLRepository.search_ids
    calls = []

    def counted(self, request, reference, after):
        calls.append(after)
        return original(self, request, reference, after)

    monkeypatch.setattr(MaterializedSQLRepository, "search_ids", counted)
    assert live.repository.search_ids(SearchRequest(page_size=1), None, None) == [
        "p:expert:1",
        "p:resume:1",
    ]
    assert calls == [None]


def test_search_details_export_use_online_people(live):
    result = live.service.search(SearchRequest(page_size=1))
    assert result.items[0].person.name == "在线人物experts"
    assert result.has_more
    next_page = live.service.search(SearchRequest(page_size=1, cursor=result.next_cursor))
    assert next_page.items[0].person.name == "在线人物resume"
    assert not next_page.has_more
    assert live.service.facts("p:expert:1").person.name == "在线人物experts"
    exported = live.service.export_page(
        ExportRequest(
            data_version=live.repository.version,
            filters=SearchRequest(page_size=1),
            expected_person_ids=["p:expert:1"],
        )
    )
    assert exported.items[0].person.name == "在线人物experts"


def test_graph_reader_uses_live_lookup_for_path_and_multihop(live):
    sql = SimpleNamespace(persons=lambda ids: pytest.fail("读取了冻结人物"))
    reader = MaterializedReader(sql, None, PathBudget(5000, 5000), live.repository.persons)
    assert reader.persons(["p:expert:1"])["p:expert:1"].name == "在线人物experts"


def test_source_unavailable_fails_explicitly(live):
    live.schema.drop_all(live.engine)
    with pytest.raises(QueryError) as error:
        live.repository.person("p:expert:1")
    assert error.value.code == "PERSON_SOURCE_UNAVAILABLE"
    assert error.value.status == 503


def test_person_source_endpoint_is_bound_to_release_before_reading(live):
    from relationship_query.update.source_config import legacy_source_config

    with pytest.raises(ValueError, match="端点"):
        live.people.check(legacy_source_config("source"), {"host": "different"})


def test_http_metadata_and_person_routes_use_live_repository(live, monkeypatch):
    monkeypatch.setenv("RELATIONSHIP_MYSQL_SOURCE_CONFIG", "test-only")
    monkeypatch.setattr(live_people, "open_people_engine", lambda *args: live.engine)
    monkeypatch.setattr(MySQLPeople, "check", lambda *args: None)
    monkeypatch.setattr(
        LiveRealGraphRepository,
        "graph_repository",
        lambda self: SimpleNamespace(client=SimpleNamespace(close=lambda: None)),
    )
    from relationship_query.update.source_config import MySQLSourceConfig, legacy_source_config

    monkeypatch.setattr(MySQLSourceConfig, "read", lambda path: legacy_source_config("source"))
    with TestClient(create_app(numeric_release_store=live.repository.directory)) as client:
        assert client.get("/api/v1/meta").json()["person_display"] == "mysql-live"
        assert (
            client.get("/api/v1/persons/suggest?q=在线")
            .json()["items"][0]["name"]
            .startswith("在线")
        )
        assert client.get("/api/v1/persons/suggest?q=LIVE-").json()["items"]
        assert client.get("/api/v1/persons/suggest?q=p:expert:1").json()["items"] == []
        result = client.post("/api/v1/persons/search", json={}).json()
        assert all(item["person"]["name"].startswith("在线") for item in result["items"])
        assert client.get("/api/v1/persons/p:expert:1/facts").json()["person"]["city"] == "杭州"


def test_open_engine_requires_private_environment_password(monkeypatch):
    from relationship_query.update.source_config import legacy_source_config

    with pytest.raises(ValueError, match="password_env"):
        live_people.open_people_engine(legacy_source_config("source"), True)


def test_live_release_requires_runtime_mysql_configuration(real_release, monkeypatch):
    import json

    monkeypatch.delenv("RELATIONSHIP_MYSQL_SOURCE_CONFIG", raising=False)
    for name in ("prepared.json", "manifest.json"):
        path = real_release / name
        data = json.loads(path.read_text())
        data["person_display"] = "mysql-live"
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="在线MySQL人物来源"):
        with TestClient(create_app(numeric_release_store=real_release)):
            pass
