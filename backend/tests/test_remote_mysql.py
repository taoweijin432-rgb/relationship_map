"""远程发布配置、TLS 与不可变来源配对；原生用例只读取专用模拟容器。"""

import hashlib
import json
import os
import shlex
import socket
import ssl
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from relationship_query.app import create_app
from relationship_query.infrastructure.mysql import (
    RemoteMySQL,
    lab_url,
    open_remote_mysql_engine,
    source_url,
)
from relationship_query.infrastructure.source_api import open_source_engine
from relationship_query.infrastructure.source_graph_model import SourceManifest
from relationship_query.infrastructure.source_releases import (
    ReleaseEvent,
    ReleaseRef,
    ReleaseState,
    bundle_digest,
    load_active,
    read_bundle,
)
from relationship_query.infrastructure.uuid_source import UUIDManifest
from relationship_query.services.query import QueryError


@pytest.fixture
def remote_manifest():
    return UUIDManifest(
        format_version=5,
        sql_guard="mutation-sequence-v1",
        source_endpoint=RemoteMySQL(host="mysql.example.test", port=3307, ca_sha256="a" * 64),
        source_database="published_people",
        space="relationship_lab_remote_test",
        source_digest="b" * 64,
        graph_digest="c" * 64,
        data_version="remote-mock-v1",
        projection_id="remote-mock-v1",
        reference_month=202611,
        counts={},
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"host": "other.example.test"},
        {"port": 3306},
        {"database": "other_database"},
        {"query": {"ssl_disabled": "true"}},
        {"query": {"unix_socket": "/tmp/mysql.sock"}},
        {"query": {"charset": "latin1"}},
        {"username": ""},
        {"password": ""},
        {"drivername": "mysql+mysqldb"},
    ],
)
def test_remote_connection_is_bound_to_release(remote_manifest, changes):
    url = make_url("mysql+pymysql://reader:secret@mysql.example.test:3307/published_people")
    value = url.set(**changes).render_as_string(hide_password=False)
    with pytest.raises(ValueError):
        source_url(value, remote_manifest.source_database, remote_manifest.source_endpoint)


def test_remote_url_escaping_and_local_writer_isolation(remote_manifest):
    url = make_url("mysql+pymysql://reader:secret@mysql.example.test:3307/published_people")
    url = url.set(password="p@ss:/?#$'", query={"charset": "utf8mb4"})
    assert (
        source_url(
            url.render_as_string(hide_password=False),
            "published_people",
            remote_manifest.source_endpoint,
        )
        == url
    )
    with pytest.raises(ValueError):
        lab_url(url.render_as_string(hide_password=False))
    with pytest.raises(ValueError):
        SourceManifest.model_validate({**remote_manifest.model_dump(), "format_version": 2})


@pytest.mark.parametrize(
    "changes",
    [
        {"format_version": 4},
        {"source_endpoint": None},
        {"sql_guard": None},
        {"source_database": "bad`name"},
        {"source_database": "a" * 65},
    ],
)
def test_remote_manifest_rejects_inconsistent_modes(remote_manifest, changes):
    with pytest.raises(ValueError):
        UUIDManifest.model_validate({**remote_manifest.model_dump(), **changes})


def test_remote_tls_context_and_ca_binding(remote_manifest, tmp_path, monkeypatch):
    ca = tmp_path / "mysql-ca.pem"
    ca.write_text("mock-ca")
    endpoint = remote_manifest.source_endpoint.model_copy(
        update={
            "ca_sha256": hashlib.sha256(ca.read_bytes()).hexdigest(),
            "connect_timeout": 7,
            "read_timeout": 12,
        }
    )
    context = ssl.create_default_context()
    monkeypatch.setattr(
        "relationship_query.infrastructure.mysql.ssl.create_default_context",
        lambda **kwargs: context,
    )
    calls = []

    def factory(url, **kwargs):
        calls.append(kwargs)
        return create_engine(url, **kwargs)

    monkeypatch.setattr("relationship_query.infrastructure.mysql.create_engine", factory)
    engine = open_remote_mysql_engine(
        "mysql+pymysql://reader:secret@mysql.example.test:3307/published_people",
        endpoint,
        ca,
    )
    try:
        args = calls[0]["connect_args"]
        assert args["ssl"] is context
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
        assert (args["connect_timeout"], args["read_timeout"]) == (7, 12)
        assert calls[0]["max_overflow"] == 0
        ca.write_text("changed-ca")
        with pytest.raises(ValueError, match="CA"):
            open_remote_mysql_engine(str(engine.url), endpoint, ca)
    finally:
        engine.dispose()


def test_remote_bundle_pins_ca_and_credentials(remote_manifest, tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(remote_manifest.model_dump_json())
    (tmp_path / "mysql-ca.pem").write_text("mock-ca")
    (tmp_path / "reader-credentials.json").write_text(
        json.dumps(
            {
                "username": "rq_" + "a" * 12,
                "password": "b" * 24,
            }
        )
    )
    (tmp_path / "reader-credentials.json").chmod(0o600)
    config = tmp_path / "api.env"
    config.write_text(
        "export RELATIONSHIP_SOURCE_API_MANIFEST="
        + shlex.quote(str(manifest))
        + "\nexport RELATIONSHIP_SOURCE_API_MYSQL_URL="
        + "mysql+pymysql://reader:secret@mysql.example.test:3307/published_people\n"
    )
    config.chmod(0o600)
    bundle = read_bundle(tmp_path)
    assert bundle.manifest.format_version == 5
    digest = bundle_digest(tmp_path)
    (tmp_path / "mysql-ca.pem").write_text("changed-ca")
    assert bundle_digest(tmp_path) != digest
    config.chmod(0o644)
    with pytest.raises(ValueError, match="600"):
        read_bundle(tmp_path)
    manifest.write_text("[]")
    with pytest.raises(ValueError, match="JSON"):
        bundle_digest(tmp_path)


@pytest.fixture(scope="module")
def remote_native():
    selected = os.environ.get("RELATIONSHIP_REMOTE_MYSQL_TEST_DIR")
    if not selected:
        pytest.skip("需显式选择独立容器远程模拟目录")
    directory = Path(selected).resolve()
    bundle = read_bundle(directory)
    assert isinstance(bundle.manifest, UUIDManifest) and bundle.manifest.format_version == 5
    endpoint = bundle.manifest.source_endpoint
    assert endpoint.host == "localhost" and bundle.manifest.source_database.startswith(
        "demo_remote_"
    )
    tokens = shlex.split((directory / "admin.env").read_text())
    assert len(tokens) == 2 and tokens[0] == "export"
    key, value = tokens[1].split("=", 1)
    assert key == "RELATIONSHIP_REMOTE_MYSQL_ADMIN_URL"
    admin_url = make_url(value)
    assert (admin_url.host, admin_url.port, admin_url.database) == (
        endpoint.host,
        endpoint.port,
        bundle.manifest.source_database,
    )
    context = ssl.create_default_context(cafile=str(directory / "mysql-ca.pem"))
    admin = create_engine(admin_url, connect_args={"ssl": context}, hide_parameters=True)
    with TestClient(
        create_app(source_manifest=directory / "manifest.json", source_mysql_url=bundle.mysql_url)
    ) as client:
        yield client, bundle, admin
    admin.dispose()


def test_native_remote_tls_and_database_enforced_readonly(remote_native):
    client, bundle, _ = remote_native
    engine = client.app.state.query_service.repository.engine
    with engine.connect() as connection:
        cipher = connection.exec_driver_sql("SHOW SESSION STATUS LIKE 'Ssl_cipher'").one()[1]
        assert cipher
        assert connection.exec_driver_sql("SELECT @@transaction_read_only").scalar_one() == 1
    # 即使绕过会话只读标志，数据库账号仍只能 SELECT。
    url = make_url(bundle.mysql_url)
    context = ssl.create_default_context(cafile=str(bundle.directory / "mysql-ca.pem"))
    writable = create_engine(url, connect_args={"ssl": context}, hide_parameters=True)
    try:
        for statement in (
            "UPDATE experts SET name=name WHERE id=1",
            "TRUNCATE TABLE experts",
            "DROP TRIGGER rq_guard_0_insert",
        ):
            with writable.connect() as connection, pytest.raises(SQLAlchemyError):
                connection.exec_driver_sql(statement)
    finally:
        writable.dispose()
    assert client.get("/api/v1/meta").json()["relation_backend"] == "nebula-materialized"


def test_native_remote_wrong_host_and_untrusted_ca_fail(remote_native):
    _, bundle, _ = remote_native
    endpoint = bundle.manifest.source_endpoint
    ca_file = bundle.directory / "mysql-ca.pem"
    wrong_host = endpoint.model_copy(update={"host": "127.0.0.1"})
    url = make_url(bundle.mysql_url).set(host="127.0.0.1")
    engine = open_remote_mysql_engine(
        url.render_as_string(hide_password=False), wrong_host, ca_file
    )
    try:
        with pytest.raises(OperationalError, match="certificate verify failed"):
            with engine.connect():
                pass
    finally:
        engine.dispose()
    ca_file = bundle.directory / "tls/untrusted-ca.pem"
    wrong_ca = endpoint.model_copy(
        update={"ca_sha256": hashlib.sha256(ca_file.read_bytes()).hexdigest()}
    )
    engine = open_remote_mysql_engine(bundle.mysql_url, wrong_ca, ca_file)
    try:
        with pytest.raises(OperationalError, match="certificate verify failed"):
            with engine.connect():
                pass
    finally:
        engine.dispose()


def test_native_remote_startup_rejects_wrong_snapshot(remote_native):
    _, bundle, _ = remote_native
    wrong = bundle.manifest.model_copy(update={"source_digest": "0" * 64})
    engine = open_source_engine(bundle.mysql_url, wrong, bundle.directory / "manifest.json")
    try:
        from relationship_query.infrastructure.uuid_api import UUIDRepository

        with pytest.raises(QueryError) as error:
            UUIDRepository(engine, wrong)
        assert error.value.code == "SOURCE_VERSION_MISMATCH"
    finally:
        engine.dispose()


def test_native_remote_privileged_account_is_rejected(remote_native):
    _, bundle, admin = remote_native
    with pytest.raises(ValueError, match="SELECT"):
        with TestClient(
            create_app(
                source_manifest=bundle.directory / "manifest.json",
                source_mysql_url=admin.url.render_as_string(hide_password=False),
            )
        ):
            pass


@pytest.mark.parametrize("plain_server", [True, False])
def test_native_remote_rejects_plain_server_and_handshake_timeout(remote_native, plain_server):
    _, bundle, _ = remote_native
    done = Event()
    with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as workers:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        port = listener.getsockname()[1]

        def server():
            with listener.accept()[0] as connection:
                connection.settimeout(3)
                if plain_server:
                    # 协议 v10 的有效握手，能力位显式缺少 CLIENT_SSL。
                    greeting = (
                        b"\x0a8.4.0\x00"
                        + struct.pack("<I", 1)
                        + b"12345678\x00"
                        + struct.pack("<HBHHB", 0x8200, 45, 2, 0, 21)
                        + b"\x00" * 10
                        + b"abcdefghijkl\x00"
                    )
                    packet = struct.pack("<I", len(greeting))[:3] + b"\x00" + greeting
                    connection.sendall(packet)
                    assert connection.recv(4096) == b""
                else:
                    done.wait(5)

        future = workers.submit(server)
        endpoint = bundle.manifest.source_endpoint.model_copy(
            update={
                "port": port,
                "read_timeout": 1,
                "connect_timeout": 1,
            }
        )
        value = make_url(bundle.mysql_url).set(port=port).render_as_string(hide_password=False)
        engine = open_remote_mysql_engine(value, endpoint, bundle.directory / "mysql-ca.pem")
        try:
            expected = "SSL is required" if plain_server else "Lost connection"
            with pytest.raises(OperationalError, match=expected):
                with engine.connect():
                    pass
        finally:
            engine.dispose()
            done.set()
            future.result(timeout=5)


def test_native_remote_disconnect_returns_storage_error(remote_native, monkeypatch):
    client, _, _ = remote_native
    engine = client.app.state.query_service.repository.engine

    def disconnected():
        raise OperationalError("SELECT", {}, Exception(2013, "simulated remote disconnect"))

    monkeypatch.setattr(engine, "connect", disconnected)
    response = client.get("/api/v1/meta")
    assert response.status_code == 503
    assert response.json()["code"] == "STORAGE_UNAVAILABLE"


def test_native_remote_release_store_and_ca_drift(remote_native, tmp_path):
    _, bundle, _ = remote_native
    ref = ReleaseRef(
        directory=str(bundle.directory),
        bundle_digest=bundle.digest,
        data_version=bundle.manifest.data_version,
        projection_id=bundle.manifest.projection_id,
    )
    state = ReleaseState(
        revision=1,
        active=ref,
        history=[
            ReleaseEvent(
                revision=1,
                action="activate",
                previous_version=None,
                data_version=ref.data_version,
                at="2026-11-09T00:00:00Z",
            )
        ],
    )
    (tmp_path / "active.json").write_text(state.model_dump_json())
    pin = load_active(tmp_path)
    with TestClient(create_app(source_release_store=tmp_path)) as client:
        assert (
            client.post("/api/v1/persons/p:expert:1/relations/search", json={}).status_code == 200
        )
        ca_file = bundle.directory / "mysql-ca.pem"
        original = ca_file.read_bytes()
        try:
            ca_file.write_bytes(original + b"\n")
            with pytest.raises(QueryError, match="激活批次"):
                pin.check()
            assert client.get("/api/v1/meta").status_code == 409
        finally:
            ca_file.write_bytes(original)


def test_native_remote_committed_mutation_is_rejected(remote_native):
    client, _, admin = remote_native
    assert client.get("/api/v1/meta").status_code == 200
    with admin.begin() as connection:
        connection.exec_driver_sql("UPDATE experts SET name='模拟远程纠正' WHERE id=1")
    response = client.get("/api/v1/meta")
    assert response.status_code == 409
    assert response.json()["code"] == "SOURCE_VERSION_MISMATCH"
