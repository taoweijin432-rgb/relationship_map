"""连接池真实等待／SQLite中断，以及PyMySQL独占连接参数的版本适配回归。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.exc import OperationalError

from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded, using_budget
from relationship_query.infrastructure.sql_deadlines import (
    DeadlineQueuePool,
    _before_execute,
    _checkin,
    _checkout,
    _connect_timeout,
    install_sql_deadlines,
)
from relationship_query.runtime.diagnostics import DiagnosticTrace, capture
from relationship_query.services.query import QueryError


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'deadline.sqlite'}",
        poolclass=DeadlineQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=3,
        connect_args={"check_same_thread": False},
    )
    install_sql_deadlines(engine)
    yield engine
    assert engine.pool.checkedout() == 0
    engine.dispose()


def test_pool_wait_obeys_remaining_budget_without_mutating_shared_timeout(engine):
    with engine.connect(), ThreadPoolExecutor(max_workers=1) as executor:

        def wait():
            started = monotonic()
            with using_budget(PathBudget(30, 100)), pytest.raises(PathBudgetExceeded):
                engine.connect()
            return monotonic() - started

        assert executor.submit(wait).result(timeout=1) < 0.5
        assert engine.pool.timeout() == 3
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1


def test_cancelling_pool_wait_does_not_lose_connection_or_take_full_timeout(engine):
    budget, entered = PathBudget(2500, 100), Event()
    with engine.connect(), ThreadPoolExecutor(max_workers=1) as executor:

        def wait():
            with using_budget(budget), pytest.raises(PathBudgetExceeded, match="cancelled"):
                entered.set()
                engine.connect()

        future = executor.submit(wait)
        assert entered.wait(1)
        budget.cancel()
        future.result(timeout=0.5)
        assert engine.pool.checkedout() == 1
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1


def test_pool_capacity_timeout_is_busy_not_dependency_failure(tmp_path):
    short = create_engine(
        f"sqlite:///{tmp_path / 'short.sqlite'}",
        poolclass=DeadlineQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.01,
    )
    install_sql_deadlines(short)
    try:
        with short.connect(), using_budget(PathBudget(1000, 100)):
            with pytest.raises(QueryError) as raised:
                short.connect()
            assert raised.value.code == "GRAPH_BUSY"
            assert short.pool.checkedout() == 1
        assert short.pool.checkedout() == 0
    finally:
        short.dispose()


@pytest.mark.parametrize("reason", ["time_limit", "sql_limit"])
def test_plain_sqlite_reads_are_interrupted_and_connection_restored(engine, reason):
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA busy_timeout=1234")
    trace = DiagnosticTrace()
    budget = (
        PathBudget(20, 100, sql_limit=10**9)
        if reason == "time_limit"
        else PathBudget(
            1000,
            100,
            sql_limit=1000,
        )
    )
    with capture(trace), using_budget(budget):
        with pytest.raises(PathBudgetExceeded, match=reason):
            with engine.connect() as connection:
                connection.exec_driver_sql(
                    "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL "
                    "SELECT x+1 FROM n WHERE x<10000000) "
                    "SELECT SUM(x) FROM n"
                ).scalar()
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 1234
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1
    assert trace.observations["sql.failure"] == 1
    assert trace.totals()["SQL.execute"]["calls"] == 1


def test_non_budget_sql_failure_retains_dependency_error(engine):
    with using_budget(PathBudget(1000, 100)), pytest.raises(OperationalError):
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT * FROM missing_table")


class Socket:
    def __init__(self):
        self.timeout = 5

    def gettimeout(self):
        return self.timeout

    def settimeout(self, value):
        self.timeout = value


def mysql_connection():
    return SimpleNamespace(
        _read_timeout=5,
        _write_timeout=7,
        _current_timeout=5,
        _sock=Socket(),
    )


def test_mysql_io_budget_and_server_hint_shrink_and_restore():
    raw = mysql_connection()
    record = SimpleNamespace(info={}, dbapi_connection=raw)
    dialect = SimpleNamespace(name="mysql")
    connection = SimpleNamespace(dialect=dialect, connection=SimpleNamespace(driver_connection=raw))
    budget = PathBudget(1000, 100)
    with using_budget(budget):
        _checkout(raw, record, None)
        assert 0 < raw._read_timeout <= 1
        budget.deadline = monotonic() + 0.01
        statement, _ = _before_execute(connection, None, "SELECT 1", (), SimpleNamespace(), False)
        assert "MAX_EXECUTION_TIME(" in statement
        assert 0 < raw._read_timeout <= 0.01
        original_hint = "SELECT /*+ MAX_EXECUTION_TIME(1) */ 1"
        assert (
            _before_execute(connection, None, original_hint, (), SimpleNamespace(), False)[0]
            == original_hint
        )
        _checkin(raw, record)
    assert (raw._read_timeout, raw._write_timeout, raw._current_timeout, raw._sock.timeout) == (
        5,
        7,
        5,
        5,
    )
    assert not record.info


def test_mysql_cleanup_failure_discards_connection():
    raw = mysql_connection()
    invalidated = []
    record = SimpleNamespace(info={}, dbapi_connection=raw, invalidate=invalidated.append)
    with using_budget(PathBudget(1000, 100)):
        _checkout(raw, record, None)
        raw._sock = None
        with pytest.raises(QueryError) as raised:
            _checkin(raw, record)
    assert raised.value.code == "STORAGE_UNAVAILABLE"
    assert len(invalidated) == 1 and not record.info


def test_connection_arguments_are_per_creation_and_tls_factory_is_preserved():
    parameters = {"connect_timeout": 3, "read_timeout": 5, "write_timeout": 7}
    before = dict(parameters)
    calls = []
    raw = mysql_connection()

    def secure_factory(*args, **kwargs):
        calls.append(kwargs)
        return raw

    record = SimpleNamespace(info={}, dbapi_connection=raw)
    with using_budget(PathBudget(100, 100)):
        assert _connect_timeout(None, record, (), parameters, factory=secure_factory) is raw
        _checkout(raw, record, None)
        _checkin(raw, record)
    assert parameters == before
    assert all(0 < value <= 0.1 for value in calls[0].values())
    assert (raw._read_timeout, raw._write_timeout, raw._current_timeout, raw._sock.timeout) == (
        5,
        7,
        5,
        5,
    )


def test_late_connection_is_closed_before_becoming_available():
    clock, closed = [0.0], []
    raw = SimpleNamespace(close=lambda: closed.append(True))

    def late_factory(**kwargs):
        clock[0] = 2.0
        return raw

    with using_budget(PathBudget(1000, 100, clock=lambda: clock[0])):
        with pytest.raises(PathBudgetExceeded, match="time_limit"):
            _connect_timeout(None, SimpleNamespace(info={}), (), {}, factory=late_factory)
    assert closed == [True]


@pytest.mark.parametrize("cancel_during_ping", [False, True])
def test_reused_connection_is_limited_before_pool_pre_ping(cancel_during_ping):
    created = []

    def create():
        raw = mysql_connection()
        raw.closed = False
        raw.rollback = lambda: None
        raw.close = lambda: setattr(raw, "closed", True)
        created.append(raw)
        return raw

    checks = []
    dialect = DefaultDialect()
    budget = PathBudget(100, 100)

    def ping(connection):
        checks.append(connection._read_timeout)
        if cancel_during_ping:
            budget.cancel()
        return True

    dialect._do_ping_w_event = ping
    pool = DeadlineQueuePool(create, pool_size=1, max_overflow=0, pre_ping=True, dialect=dialect)
    event.listen(pool, "checkout", _checkout)
    event.listen(pool, "checkin", _checkin)
    pool.connect().close()
    with using_budget(budget):
        if cancel_during_ping:
            with pytest.raises(PathBudgetExceeded, match="cancelled"):
                pool.connect()
        else:
            connection = pool.connect()
            connection.close()
    assert len(checks) == 1 and 0 < checks[0] <= 0.1
    assert pool.checkedout() == 0
    if cancel_during_ping:
        # SQLAlchemy会关闭checkout失败的DBAPI连接，不要求死连接恢复参数。
        assert created[0].closed
        recovered = pool.connect()
        assert recovered.dbapi_connection is created[1]
        assert created[1]._read_timeout == 5
        recovered.close()
    else:
        assert created[0]._read_timeout == 5 and not created[0].closed
    pool.dispose()
