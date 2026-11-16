"""离线防护检查与显式启用的本机 MySQL 集成验证，不连接业务数据库。"""

import json
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError

from relationship_query.app import create_app
from relationship_query.contracts import PathRequest
from relationship_query.domain.models import Dataset
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded, using_budget
from relationship_query.infrastructure.mysql import (
    MySQLPathRepository,
    lab_url,
    mysql_path_timeout,
    open_mysql_engine,
)
from relationship_query.infrastructure.mysql_dataset import import_snapshot
from relationship_query.infrastructure.read_model import dataset_meta, facts
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.infrastructure.sqlite import load_dataset, open_engine
from relationship_query.services.paths import PathService
from relationship_query.services.query import QueryService
from tests.differential_data import differential_dataset
from tests.reference_oracle import scoped_proofs
from tests.test_paths import _expected_paths, _signatures
from tests.test_query_baseline import (
    CASES,
    GOLDEN_DATA,
    actual_proofs,
    all_items,
)
from tests.test_query_baseline import (
    test_independent_500_person_differential as run_independent_queries,
)
from tests.test_query_baseline import (
    test_scoped_500_person_differential as run_scoped_queries,
)
from tests.test_snapshot_rehearsal import (
    test_snapshot_corrections_and_restart_cursor as run_snapshot_correction,
)

LIVE = pytest.mark.skipif(
    os.environ.get("RELATIONSHIP_MYSQL_TEST") != "1", reason="显式启用本机 MySQL 集成测试"
)


@pytest.mark.parametrize(
    "url",
    [
        "mysql+pymysql://root@127.0.0.1/business",
        "mysql+pymysql://root@remote/relationship_lab_test",
        "mysql+pymysql://root@127.0.0.1/relationship_lab_test?unix_socket=/tmp/mysql.sock",
        "mysql+pymysql://root@127.0.0.1/relationship_lab_test?charset=latin1",
        "sqlite:///relationship_lab_test",
    ],
)
def test_lab_url_rejects_other_targets(url: str) -> None:
    with pytest.raises(ValueError):
        lab_url(url)


def test_only_confirmed_mysql_timeout_is_budget() -> None:
    for code in (3024, 2013, 1205, 1045):
        error = OperationalError("query", {}, Exception(code, "fake failure"))
        assert mysql_path_timeout(error) == (code == 3024)


@contextmanager
def new_lab() -> Iterator[str]:
    admin = make_url(
        os.environ.get("RELATIONSHIP_MYSQL_ADMIN_URL", "mysql+pymysql://root@127.0.0.1:3306")
    )
    assert admin.host in {"localhost", "127.0.0.1"} and not admin.database and not admin.query
    name = "relationship_lab_test_" + secrets.token_hex(6)
    engine = create_engine(admin, hide_parameters=True)
    created = False
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin"
            )
            created = True
        yield admin.set(database=name).render_as_string(hide_password=False)
    finally:
        # 只清理本次 CREATE 成功后生成的随机实验库，不接受外部库名。
        if created:
            with engine.connect() as connection:
                connection.exec_driver_sql(f"DROP DATABASE `{name}`")
        engine.dispose()


@pytest.fixture(scope="module")
def mysql_lab() -> Iterator[tuple[str, Engine]]:
    if os.environ.get("RELATIONSHIP_MYSQL_TEST") != "1":
        pytest.skip("显式启用本机 MySQL 集成测试")
    with new_lab() as url:
        engine = open_mysql_engine(url, writable=True)
        load_dataset(engine, Dataset.model_validate_json(GOLDEN_DATA.read_text()))
        yield url, engine
        engine.dispose()


@pytest.mark.parametrize("case", CASES["searches"], ids=lambda case: case["name"])
@pytest.mark.parametrize("page_size", [1, 7, 20])
def test_mysql_hand_checked_pages(
    mysql_lab: tuple[str, Engine], case: dict, page_size: int
) -> None:
    service = QueryService(SQLRepository(mysql_lab[1]))
    result = all_items(service, case["filters"], case.get("reference"), page_size)
    assert [item.person.id for item in result] == case["expected"]


@pytest.mark.parametrize("case", CASES["evidence"], ids=lambda case: case["candidate"])
def test_mysql_hand_checked_proofs(mysql_lab: tuple[str, Engine], case: dict) -> None:
    service = QueryService(SQLRepository(mysql_lab[1]))
    expected = [
        (kind, entity, a, b, tuple(window) if window else None)
        for kind, entity, a, b, window in case["expected"]
    ]
    assert sorted(actual_proofs(service, "p:01", case["candidate"])) == sorted(expected)


@LIVE
@pytest.mark.parametrize("scoped", [False, True])
def test_mysql_independent_500_people(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scoped: bool
) -> None:
    import tests.test_query_baseline as baseline

    with new_lab() as url:
        engine = open_mysql_engine(url, writable=True)
        monkeypatch.setattr(baseline, "open_engine", lambda _path: engine)
        (run_scoped_queries if scoped else run_independent_queries)(tmp_path)


@pytest.mark.parametrize("kind", [None, "same_school", "same_company", "same_company_overlap"])
@pytest.mark.parametrize("source", [None, "expert"])
def test_mysql_paths(mysql_lab: tuple[str, Engine], kind: str | None, source: str | None) -> None:
    query = QueryService(SQLRepository(mysql_lab[1]))
    service = PathService(
        MySQLPathRepository(
            mysql_lab[1], query.repository.version, query.repository.reference_month
        ),
        query,
    )
    request = PathRequest(
        reference_id="p:01",
        candidate_id="p:07",
        scope={"relation_type": kind},
        intermediate_source=source,
    )
    actual = service.search(request).model_dump()
    expected = _expected_paths(
        json.loads(GOLDEN_DATA.read_text()), "p:01", "p:07", {"relation_type": kind}, source
    )
    assert actual["search_complete"]
    assert [path["intermediate"]["id"] for path in actual["paths"]] == [
        item[0] for item in expected
    ]
    for path, (_, first, second) in zip(actual["paths"], expected):
        assert sorted(_signatures(path["segments"][0])) == sorted(first)
        assert sorted(_signatures(path["segments"][1])) == sorted(second)


@LIVE
def test_mysql_all_candidates_match_independent_oracle() -> None:
    raw = differential_dataset()
    with new_lab() as url:
        engine = open_mysql_engine(url, writable=True)
        try:
            load_dataset(engine, Dataset.model_validate(raw))
            repo = SQLRepository(engine)
            paths = MySQLPathRepository(engine, repo.version, repo.reference_month)
            for reference in ("d:0000", "d:0001", "d:0002"):
                for kind in (None, "same_company", "same_school", "same_company_overlap"):
                    for source in (None, "expert"):
                        scope = {"relation_type": kind}
                        expected = sorted(
                            person["id"]
                            for person in raw["people"]
                            if person["active"]
                            and person["id"] not in {reference, "d:0003"}
                            and (source is None or source in person["sources"])
                            and scoped_proofs(raw, reference, person["id"], scope)
                        )
                        request = PathRequest.model_validate(
                            dict(
                                reference_id=reference,
                                candidate_id="d:0003",
                                scope=scope,
                                intermediate_source=source,
                                limits={"candidate_limit": 500},
                            )
                        )
                        with paths.session(PathBudget(10000, 5000)) as reader:
                            assert reader.candidates(request) == expected
        finally:
            engine.dispose()


def test_mysql_read_only_api_and_connection_cleanup(mysql_lab: tuple[str, Engine]) -> None:
    with TestClient(create_app(mysql_url=mysql_lab[0])) as client:
        assert client.get("/api/v1/meta").status_code == 200
        assert client.post("/api/v1/persons/search", json={}).status_code == 200
        assert client.post("/api/v1/persons/p:01/relations/search", json={}).status_code == 200
        assert (
            client.post(
                "/api/v1/relations/paths", json={"reference_id": "p:01", "candidate_id": "p:07"}
            ).status_code
            == 200
        )
        assert client.get("/api/v1/persons/missing/facts").status_code == 404
    reader = open_mysql_engine(mysql_lab[0])
    try:
        with reader.connect() as connection:
            with pytest.raises(OperationalError):
                connection.execute(text("UPDATE demo_dataset SET version = 'forbidden'"))
        with reader.connect() as connection:
            assert connection.scalar(select(dataset_meta.c.version)) == "handoff-example-v1"
    finally:
        reader.dispose()


def test_mysql_timeout_cleans_hint_and_pool(mysql_lab: tuple[str, Engine]) -> None:
    repo = SQLRepository(mysql_lab[1])
    paths = MySQLPathRepository(mysql_lab[1], repo.version, repo.reference_month)
    with pytest.raises(PathBudgetExceeded) as raised:
        with paths.session(PathBudget(5, 100)) as reader:
            reader.connection.exec_driver_sql("SELECT SLEEP(0.1)")
    assert raised.value.reason == "time_limit"
    with mysql_lab[1].connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
    assert mysql_lab[1].pool.checkedout() == 0


def test_mysql_request_io_state_and_timeout_recovery(mysql_lab: tuple[str, Engine]) -> None:
    engine = mysql_lab[1]
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        original = (raw._read_timeout, raw._write_timeout)
        original_execution = connection.exec_driver_sql(
            "SELECT @@session.max_execution_time"
        ).scalar()
    with using_budget(PathBudget(500, 100)), engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1
        raw = connection.connection.driver_connection
        assert 0 < raw._read_timeout <= 0.5
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        assert (raw._read_timeout, raw._write_timeout) == original
        assert (
            connection.exec_driver_sql("SELECT @@session.max_execution_time").scalar()
            == original_execution
        )
    with pytest.raises(PathBudgetExceeded, match="time_limit"):
        with using_budget(PathBudget(20, 100)) as budget, engine.connect() as connection:
            connection.exec_driver_sql("SELECT SLEEP(0.2)").scalar()
            budget.check()
    assert engine.pool.checkedout() == 0
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        assert (raw._read_timeout, raw._write_timeout) == original
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1


@LIVE
def test_mysql_snapshot_import_read_only_and_no_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "input.sqlite"
    source = open_engine(path)
    dataset = Dataset.model_validate_json(GOLDEN_DATA.read_text())
    load_dataset(source, dataset)
    source.dispose()
    before = path.read_bytes()
    with new_lab() as url:
        target = open_mysql_engine(url, writable=True)
        try:
            result = import_snapshot(path, target)
            assert result["people"] == len(dataset.people)
            assert result["facts"] == len(dataset.facts)
            assert path.read_bytes() == before
            with pytest.raises(ValueError, match="必须为空"):
                import_snapshot(path, target)
            assert target.connect().close() is None
        finally:
            target.dispose()


@LIVE
def test_mysql_invalid_snapshot_creates_no_tables(tmp_path: Path) -> None:
    path = tmp_path / "invalid.sqlite"
    source = open_engine(path)
    load_dataset(source, Dataset.model_validate_json(GOLDEN_DATA.read_text()))
    with source.begin() as connection:
        connection.execute(facts.update().values(person_id="missing"))
    source.dispose()
    before = path.read_bytes()
    with new_lab() as url:
        target = open_mysql_engine(url, writable=True)
        try:
            with pytest.raises(ValueError, match="未关联"):
                import_snapshot(path, target)
            assert inspect(target).get_table_names() == []
            assert path.read_bytes() == before
        finally:
            target.dispose()


@LIVE
def test_mysql_binary_ids_literal_prefix_and_unicode(tmp_path: Path) -> None:
    raw = json.loads(GOLDEN_DATA.read_text())
    for identity, name in [
        ("P:A", "Alice"),
        ("p:a", "alice"),
        ("p:a ", "Álice"),
        ("p:emoji😀", "字%_\\名😀"),
    ]:
        raw["people"].append(
            dict(
                id=identity, name=name, city="虚构城市", headline="字面匹配样例", sources=["resume"]
            )
        )
    dataset = Dataset.model_validate(raw)
    source = open_engine(tmp_path / "prefix.sqlite")
    load_dataset(source, dataset)
    with new_lab() as url:
        target = open_mysql_engine(url, writable=True)
        try:
            load_dataset(target, dataset)
            a, b = SQLRepository(source), SQLRepository(target)
            for keyword in ("a", "A", "Á", "字%_\\", "P:", "p:a", "😀", ".*"):
                assert [p.id for p in a.suggest_people(keyword, 50)] == [
                    p.id for p in b.suggest_people(keyword, 50)
                ], keyword
            assert b.person("p:a").name == "alice"
            assert b.person("p:a ").name == "Álice"
            assert b.person("P:A").name == "Alice"
            assert [p.person.id for p in all_items(QueryService(a), {}, None, 1)] == [
                p.person.id for p in all_items(QueryService(b), {}, None, 1)
            ]
        finally:
            target.dispose()
    source.dispose()


@LIVE
@pytest.mark.parametrize(
    "correction",
    ["invalidate_work", "correct_company", "correct_school", "upstream_person_mapping"],
)
def test_mysql_stopped_snapshot_corrections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, correction: str
) -> None:
    import tests.test_snapshot_rehearsal as rehearsal

    with new_lab() as url:
        engine = open_mysql_engine(url, writable=True)

        def publish(_path: Path, payload: dict) -> None:
            # 仅在临时测试库及服务生命周期之间演练，不给真实实验入口开放 reset。
            load_dataset(engine, Dataset.model_validate(payload), reset=True)

        monkeypatch.setattr(rehearsal, "publish_stopped_snapshot", publish)
        monkeypatch.setattr(rehearsal, "create_app", lambda _path: create_app(mysql_url=url))
        try:
            run_snapshot_correction(tmp_path, correction)
        finally:
            engine.dispose()
