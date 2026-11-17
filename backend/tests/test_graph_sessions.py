"""独占复用、失效恢复、截止时间及关闭时在途会话的回归。"""

import os
import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, Thread
from time import sleep

import pytest
from pydantic import SecretStr

from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure import graph_sessions
from relationship_query.infrastructure.graph_client import GraphClient, GraphDependencyError
from relationship_query.infrastructure.graph_model import ProjectionManifest, ReaderCredentials


def graph_client() -> GraphClient:
    manifest = ProjectionManifest(
        space="relationship_lab_sessions",
        projection_id="test",
        data_version="v1",
        reference_month=202611,
        source_digest="a" * 64,
        counts={},
    )
    return GraphClient(
        manifest, ReaderCredentials(username="rq_" + "a" * 12, password=SecretStr("a" * 24))
    )


class Result:
    def __init__(self, code=0):
        self.code = code

    def error_code(self):
        return self.code

    def error_msg(self):
        return "test-only error"

    def is_succeeded(self):
        return self.code == 0

    def as_primitive(self):
        return [{"value": 1}]


@pytest.fixture
def transport(monkeypatch):
    instances = []

    class Session:
        def __init__(self, _credentials, budget):
            budget.check()
            self.closed = False
            self.discarded = False
            self.lock = Lock()
            self.calls = 0
            self.action = lambda: Result()
            instances.append(self)

        def execute(self, statement, budget):
            assert self.lock.acquire(blocking=False), "same session used concurrently"
            try:
                assert not self.closed
                budget.check()
                self.calls += 1
                sleep(0.001)
                return self.action()
            finally:
                self.lock.release()

        def close(self):
            self.closed = True

        def release(self):
            self.close()

        def discard(self):
            self.discarded = True
            self.close()

    monkeypatch.setattr(graph_sessions, "GraphSession", Session)
    return instances


def test_reuses_one_session_and_closes_idempotently(transport):
    graph = graph_client()
    for _ in range(10):
        assert graph.execute("YIELD 1", PathBudget(3000, 100), 1) == [{"value": 1}]
    assert len(transport) == 1 and transport[0].calls == 10
    graph.close()
    graph.close()
    assert transport[0].closed
    with pytest.raises(GraphDependencyError):
        graph.execute("YIELD 1", PathBudget(3000, 100), 1)


def test_four_workers_use_exclusive_bounded_sessions(transport):
    graph = graph_client()
    try:

        def worker(_):
            for _ in range(100):
                graph.execute("YIELD 1", PathBudget(3000, 100), 1)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(worker, range(4)))
        assert 1 <= len(transport) <= 4
        assert sum(item.calls for item in transport) == 400
    finally:
        graph.close()
    assert all(item.closed for item in transport)


@pytest.mark.parametrize("code", [-1002, -1003])
def test_expired_session_retries_once_with_new_identity(transport, code):
    graph = graph_client()
    try:
        graph.execute("YIELD 1", PathBudget(3000, 100), 1)
        transport[0].action = lambda: Result(code)
        budget = PathBudget(3000, 100)
        assert graph.execute("YIELD 1", budget, 1) == [{"value": 1}]
        assert budget.graph_calls == 2
        assert len(transport) == 2 and transport[0].discarded
    finally:
        graph.close()


@pytest.mark.parametrize("raw_thrift", [False, True])
def test_broken_transport_is_logged_without_statement_or_credentials(transport, caplog, raw_thrift):
    from nebula3.Exception import IOErrorException
    from nebula3.fbthrift.transport.TTransport import TTransportException

    graph = graph_client()
    try:
        graph.execute("YIELD 1", PathBudget(3000, 100), 1)

        def broken():
            if raw_thrift:
                raise TTransportException(TTransportException.END_OF_FILE, "sensitive detail")
            raise IOErrorException(IOErrorException.E_CONNECT_BROKEN, "sensitive detail")

        transport[0].action = broken
        with pytest.raises(GraphDependencyError):
            graph.execute("YIELD 'sensitive statement'", PathBudget(3000, 100), 1)
        name = "TTransportException" if raw_thrift else "IOErrorException"
        assert f"graph dependency failure: {name} type=" in caplog.text
        assert "sensitive" not in caplog.text
        assert transport[0].discarded
        assert len(transport) == 1
        graph.execute("YIELD 1", PathBudget(3000, 100), 1)
        assert len(transport) == 2
    finally:
        graph.close()


@pytest.mark.parametrize("raw_thrift", [False, True])
def test_timeout_discards_connection_without_retry_and_next_request_recovers(transport, raw_thrift):
    from nebula3.Exception import IOErrorException
    from nebula3.fbthrift.transport.TTransport import TTransportException

    graph = graph_client()
    try:
        graph.execute("YIELD 1", PathBudget(3000, 100), 1)

        def timeout():
            if raw_thrift:
                raise TTransportException(TTransportException.TIMED_OUT, "test timeout")
            raise IOErrorException(IOErrorException.E_TIMEOUT, "test timeout")

        transport[0].action = timeout
        with pytest.raises(PathBudgetExceeded):
            graph.execute("YIELD 1", PathBudget(3000, 100), 1)
        assert len(transport) == 1 and transport[0].discarded
        graph.execute("YIELD 1", PathBudget(3000, 100), 1)
        assert len(transport) == 2
    finally:
        graph.close()


@pytest.mark.parametrize("timeout", [False, True])
def test_raw_handshake_failure_closes_socket_releases_creation_lock_and_http_maps_error(
    monkeypatch, client, timeout, caplog
):
    from nebula3.fbthrift.transport.TTransport import TTransportException

    events = []

    class BrokenConnection:
        def open(self, _host, _port, _timeout):
            events.append("open")
            code = TTransportException.TIMED_OUT if timeout else TTransportException.END_OF_FILE
            raise TTransportException(code, "private handshake detail")

        def close(self):
            events.append("close")

    monkeypatch.setattr(graph_sessions, "DeadlineConnection", BrokenConnection)
    # 使用真实GraphSession构造及GraphClient边界，SQL业务仅作为实际HTTP承载。
    graph = graph_client()
    try:

        def operation(*_args):
            return graph.execute("YIELD 'private statement'", PathBudget(3000, 100), 1)

        monkeypatch.setattr(client.app.state.query_service, "search", operation)
        response = client.post("/api/v1/persons/search", json={})
        assert response.status_code == 503
        assert response.json()["code"] == ("GRAPH_QUERY_LIMIT" if timeout else "GRAPH_UNAVAILABLE")
        assert events == ["open", "close"]  # 不自动重试握手断流或超时。
        assert graph.sessions._creation.acquire(blocking=False)
        graph.sessions._creation.release()
        assert all(graph.slots.acquire(blocking=False) for _ in range(4))
        for _ in range(4):
            graph.slots.release()
        assert "private" not in response.text and "private" not in caplog.text
    finally:
        graph.close()


@pytest.mark.skipif(
    os.environ.get("RELATIONSHIP_GRAPH_TEST") != "1", reason="显式启用本机TCP握手故障验收"
)
@pytest.mark.parametrize("timeout", [False, True])
def test_actual_sdk_handshake_disconnect_and_timeout_are_bounded(timeout):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2)
    stop, received = Event(), Event()
    errors = []

    def server():
        try:
            with listener.accept()[0] as connection:
                connection.settimeout(2)
                if connection.recv(4096):
                    received.set()
                if timeout:
                    stop.wait(2)
        except OSError as error:
            errors.append(type(error).__name__)

    worker = Thread(target=server)
    graph = graph_client()
    # 固定凭据模型不为实验放宽；仅本次独立客户端连接实际临时监听端口。
    graph.sessions.credentials = graph.credentials.model_copy(
        update={"port": listener.getsockname()[1]}
    )
    worker.start()
    try:
        expected = PathBudgetExceeded if timeout else GraphDependencyError
        with pytest.raises(expected):
            graph.execute("YIELD 1", PathBudget(200, 100), 1)
        assert received.is_set()
        assert all(graph.slots.acquire(blocking=False) for _ in range(4))
        for _ in range(4):
            graph.slots.release()
    finally:
        stop.set()
        listener.close()
        worker.join(timeout=3)
        graph.close()
    assert not worker.is_alive() and not errors


def test_server_rejection_preserves_connection_without_retry(transport):
    graph = graph_client()
    try:
        graph.execute("YIELD 1", PathBudget(3000, 100), 1)
        transport[0].action = lambda: Result(-1005)
        budget = PathBudget(3000, 100)
        with pytest.raises(GraphDependencyError):
            graph.execute("YIELD 1", budget, 1)
        assert budget.graph_calls == 1 and not transport[0].closed
    finally:
        graph.close()


def test_shutdown_waits_for_borrowed_session_to_return(transport):
    graph = graph_client()
    graph.execute("YIELD 1", PathBudget(3000, 100), 1)
    entered, finish = Event(), Event()

    def blocked():
        entered.set()
        assert finish.wait(3)
        return Result()

    transport[0].action = blocked
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(graph.execute, "YIELD 1", PathBudget(3000, 100), 1)
        assert entered.wait(3)
        graph.close()
        assert not transport[0].closed
        finish.set()
        assert future.result() == [{"value": 1}]
    assert transport[0].closed


def test_expired_budget_never_creates_a_session(transport):
    graph = graph_client()
    budget = PathBudget(1, 100, clock=lambda: 0)
    budget.clock = lambda: 1
    with pytest.raises(PathBudgetExceeded):
        graph.execute("YIELD 1", budget, 1)
    assert not transport
    graph.close()


def test_each_reused_rpc_updates_socket_timeout_from_remaining_budget(monkeypatch):
    from types import SimpleNamespace

    elapsed, timeouts = [0.0], []

    class Connection:
        def open(self, _host, _port, milliseconds):
            timeouts.append(milliseconds)

        def set_timeout(self, milliseconds):
            timeouts.append(milliseconds)

        def authenticate(self, *_args):
            elapsed[0] = 0.1
            return SimpleNamespace(get_session_id=lambda: 1, get_timezone_offset=lambda: 0)

        def execute_parameter(self, *_args):
            return SimpleNamespace(data=None, error_code=0)

        def close(self):
            pass

    monkeypatch.setattr(graph_sessions, "DeadlineConnection", Connection)
    graph = graph_client()
    scope = PathBudget(500, 100, clock=lambda: elapsed[0])
    session = graph_sessions.GraphSession(graph.credentials, scope)
    session.execute("YIELD 1", scope)
    assert 399 <= timeouts[-1] <= 400
    elapsed[0] = 0.3
    session.execute("YIELD 1", scope)
    assert 199 <= timeouts[-1] <= 201
    session.close()
    graph.close()


def test_sdk_timeout_reopen_hook_only_closes(monkeypatch):
    connection = graph_sessions.DeadlineConnection()
    closed = []
    monkeypatch.setattr(connection, "close", lambda: closed.append(True))
    monkeypatch.setattr(connection, "open", lambda *_args: pytest.fail("unexpected reconnect"))
    connection._reopen()
    assert closed == [True]


def test_authentication_finishing_after_deadline_releases_its_session(monkeypatch):
    from types import SimpleNamespace

    clock, released = [0.0], []

    class Connection:
        def open(self, *_args):
            pass

        def set_timeout(self, *_args):
            pass

        def authenticate(self, *_args):
            clock[0] = 2
            return SimpleNamespace(get_session_id=lambda: 123)

        def signout(self, session_id):
            released.append(session_id)

        def close(self):
            pass

    monkeypatch.setattr(graph_sessions, "DeadlineConnection", Connection)
    graph = graph_client()
    with pytest.raises(PathBudgetExceeded):
        graph_sessions.GraphSession(
            graph.credentials, PathBudget(1000, 100, clock=lambda: clock[0])
        )
    assert released == [123]
    graph.close()
