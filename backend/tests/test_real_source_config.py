"""来源拓扑、采集入口路由与续采保护，全部使用只读数据库替身。"""

import importlib.util
import json
import ssl
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from relationship_query.update.source_config import (
    MySQLReadEndpoint,
    MySQLSourceConfig,
    legacy_source_config,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def capture_module():
    path = ROOT / "scripts/capture_real_graph_sources.py"
    spec = importlib.util.spec_from_file_location("real_source_capture_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_config(unified=False):
    connections = {
        "mapping": MySQLReadEndpoint(
            host="mapping.example.test", database="graph_input", user="mapping_reader"
        )
    }
    if not unified:
        connections["original"] = MySQLReadEndpoint(
            host="people.example.test", port=3307, database="people_input", user="people_reader"
        )
    return MySQLSourceConfig(
        connections=connections,
        entity_source="mapping",
        person_source="mapping" if unified else "original",
    )


@pytest.mark.parametrize("unified", [False, True])
def test_roles_select_split_or_shared_connection(unified):
    config = source_config(unified)
    assert config.endpoint("entities").database == "graph_input"
    assert (config.endpoint("people") == config.endpoint("entities")) == unified


@pytest.mark.parametrize(
    "change",
    [
        {"person_source": "missing"},
        {"entity_source": "missing"},
        {"format": "unrecognized"},
        {"password": "fictional-secret"},
    ],
)
def test_invalid_configuration_rejected(change):
    with pytest.raises(ValidationError):
        MySQLSourceConfig.model_validate({**source_config().model_dump(), **change})


@pytest.mark.parametrize("port", [0, 65536, True, "3306"])
def test_connection_port_is_strict(port):
    with pytest.raises(ValidationError):
        MySQLReadEndpoint(host="example.test", database="source", user="reader", port=port)


def test_certificate_resolves_against_configuration_directory(tmp_path):
    config = source_config().model_dump()
    config["connections"]["mapping"]["tls_ca_file"] = "certificates/source-ca.pem"
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(config))
    assert MySQLSourceConfig.read(path).endpoint("entities").tls_ca_file == str(
        tmp_path / "certificates/source-ca.pem"
    )


@pytest.mark.parametrize("unified", [False, True])
@pytest.mark.parametrize("relation_only", [False, True])
def test_capture_entrypoint_routes_both_roles_and_preserves_raw_ids(
    tmp_path, monkeypatch, capture_module, unified, relation_only
):
    config = source_config(unified)
    sessions = []
    mapping = {
        "id": 101,
        "source_system": "expert",
        "source_person_id": 17,
        "source_table": "experts_work_experience",
        "source_field_id": 23,
        "deleted_at": None,
    }
    data = {table: [] for table in capture_module.ENTITY_TABLES}
    data.update({table: [] for tables in capture_module.PERSON_TABLES.values() for table in tables})
    data["graph_edge_mapping"] = [mapping]
    data["experts"] = [
        {"id": 17, "serial_number": "mock-17", "name": "模拟人物", "deleted_at": None}
    ]
    data["experts_work_experience"] = [{"id": 23, "expert_id": 17, "start_date": "2020-01-01"}]
    columns = [
        {"TABLE_NAME": table, "COLUMN_NAME": column}
        for tables in capture_module.PERSON_TABLES.values()
        for table in tables
        for column in (data[table][0] if data[table] else {"id": None})
    ]
    cursor = SimpleNamespace(
        execute=lambda *args: None,
        fetchall=lambda: columns,
    )

    @contextmanager
    def query_cursor():
        yield cursor

    @contextmanager
    def session(endpoint, insecure_tls):
        assert insecure_tls is False
        sessions.append(endpoint)
        yield SimpleNamespace(cursor=query_cursor)

    def metadata(connection, endpoint, insecure_tls):
        return {"host": endpoint.host, "port": endpoint.port, "database": endpoint.database}

    def read_rows(connection, table, columns=None, ids=None):
        if relation_only and table in {"experts", "resume"} and columns is not None:
            assert not {"name", "city", "job_name"}.intersection(columns)
        records = [row for row in data[table] if ids is None or row["id"] in ids]
        return (
            records if columns is None else [{key: row[key] for key in columns} for row in records]
        )

    monkeypatch.setattr(capture_module, "source_session", session)
    monkeypatch.setattr(capture_module, "source_metadata", metadata)
    monkeypatch.setattr(capture_module, "read_rows", read_rows)
    output = tmp_path / "capture"
    capture_module.capture_sources(output, config, relation_only=relation_only)
    people = json.loads((output / "person-source.json").read_text())
    assert people["tables"]["experts"][0]["id"] == 17
    assert people["tables"]["experts_work_experience"][0]["id"] == 23
    assert people["tables"]["experts"][0]["name"] == ("人物" if relation_only else "模拟人物")
    assert people["person_display"] == ("mysql-live" if relation_only else "snapshot")
    assert sessions == [config.endpoint("entities"), config.endpoint("people")]
    sessions.clear()
    capture_module.capture_sources(output, config, resume=True, relation_only=relation_only)
    assert sessions == []


@pytest.mark.parametrize("role", ["entities", "people"])
@pytest.mark.parametrize(
    "field,value", [("host", "other.test"), ("port", 3310), ("database", "other")]
)
def test_resume_rejects_endpoint_change_before_any_read(
    tmp_path, monkeypatch, capture_module, role, field, value
):
    config = source_config()
    filename = "entity-source.json" if role == "entities" else "person-source.json"
    endpoint = config.endpoint(role)
    metadata = {"host": endpoint.host, "port": endpoint.port, "database": endpoint.database}
    metadata[field] = value
    (tmp_path / filename).write_text(json.dumps({"metadata": metadata}))

    def unexpected_read(*args):
        pytest.fail("来源校验应先于数据库访问")

    monkeypatch.setattr(capture_module, "capture_entities", unexpected_read)
    monkeypatch.setattr(capture_module, "capture_people", unexpected_read)
    with pytest.raises(ValueError, match="冻结来源"):
        capture_module.capture_sources(tmp_path, config, resume=True)


def test_connection_uses_profile_port_password_reference_and_verified_tls(
    monkeypatch, capture_module
):
    options = {}
    sentinel = object()

    def connect(**settings):
        options.update(settings)
        return sentinel

    monkeypatch.setenv("TEST_REAL_SOURCE_PASSWORD", "fictional-password")
    monkeypatch.setattr(capture_module, "TLSConnection", connect)
    endpoint = MySQLReadEndpoint(
        host="source.example.test",
        port=3307,
        database="input",
        user="reader",
        password_env="TEST_REAL_SOURCE_PASSWORD",
    )
    assert capture_module.connect_source(endpoint, False) is sentinel
    assert (options["host"], options["port"], options["user"]) == (
        "source.example.test",
        3307,
        "reader",
    )
    assert options["password"] == "fictional-password"
    assert options["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert options["ssl"].check_hostname is True


def test_missing_password_reference_stops_before_connect(monkeypatch, capture_module):
    monkeypatch.delenv("TEST_REAL_SOURCE_PASSWORD", raising=False)
    endpoint = (
        source_config()
        .endpoint("entities")
        .model_copy(update={"password_env": "TEST_REAL_SOURCE_PASSWORD"})
    )
    with pytest.raises(ValueError, match="环境变量未设置"):
        capture_module.connect_source(endpoint, False)


@pytest.mark.parametrize("configured", [False, True])
def test_cli_supports_legacy_and_config_file(tmp_path, monkeypatch, capture_module, configured):
    config = source_config(True)
    path = tmp_path / "sources.json"
    path.write_text(config.model_dump_json())
    arguments = (
        ["--source-config", str(path)] if configured else ["--person-database", "old_people"]
    )
    monkeypatch.setattr(sys, "argv", ["capture", "--output", str(tmp_path / "output"), *arguments])
    called = []
    monkeypatch.setattr(
        capture_module, "capture_sources", lambda output, sources, **kwargs: called.append(sources)
    )
    capture_module.main()
    assert called == [config if configured else legacy_source_config("old_people")]
