"""使用单连接真实池验证请求状态归还，避免下一请求继承已耗尽的锁等待时间。"""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.fixtures import make_dataset
from relationship_query.infrastructure.sqlite import load_dataset
from relationship_query.infrastructure.sqlite_paths import SQLitePathRepository
from relationship_query.services.query import QueryError


class CleanupFailureConnection(sqlite3.Connection):
    fail_cleanup = ""

    def execute(self, statement, *args, **kwargs):
        if self.fail_cleanup == "timeout" and statement == "PRAGMA busy_timeout=5000":
            raise sqlite3.OperationalError("test restoration failure")
        return super().execute(statement, *args, **kwargs)

    def set_progress_handler(self, callback, steps):
        if self.fail_cleanup == "progress" and callback is None:
            raise sqlite3.OperationalError("test progress cleanup failure")
        return super().set_progress_handler(callback, steps)

    def rollback(self):
        if self.fail_cleanup == "rollback":
            raise sqlite3.OperationalError("test rollback failure")
        return super().rollback()


@pytest.fixture
def database(tmp_path: Path):
    path = tmp_path / "state.sqlite"
    engine = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(path, factory=CleanupFailureConnection),
        pool_size=1,
        max_overflow=0,
        poolclass=QueuePool,
    )
    data = make_dataset()
    load_dataset(engine, data)
    yield engine, SQLitePathRepository(engine, data.version, data.reference_month)
    engine.dispose()


@pytest.mark.parametrize("original", [0, 5000, 12345])
@pytest.mark.parametrize("exit_kind", ["normal", "exception", "budget", "sql_interrupt"])
def test_timeout_and_progress_are_restored_on_every_exit(database, original, exit_kind):
    engine, repository = database
    with engine.connect() as connection:
        connection.exec_driver_sql(f"PRAGMA busy_timeout={original}")
        identity = connection.connection.driver_connection
    clock = [0.0]
    budget = PathBudget(1000, 100, clock=lambda: clock[0])
    expected = {
        "exception": ValueError,
        "budget": PathBudgetExceeded,
        "sql_interrupt": PathBudgetExceeded,
    }

    def request():
        with repository.session(budget) as reader:
            assert reader.connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 1000
            if exit_kind == "exception":
                raise ValueError("test failure")
            if exit_kind == "budget":
                clock[0] = 2
                budget.check()
            if exit_kind == "sql_interrupt":
                clock[0] = 2
                reader.connection.exec_driver_sql(
                    "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<10000) "
                    "SELECT SUM(x) FROM n"
                ).scalar()

    if exit_kind == "normal":
        request()
    else:
        with pytest.raises(expected[exit_kind]):
            request()
    assert engine.pool.checkedout() == 0
    with engine.connect() as connection:
        assert connection.connection.driver_connection is identity
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == original
        # 已过期预算的progress handler必须移除，否则下一请求的长语句会被中断。
        assert connection.exec_driver_sql(
            "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<10000) "
            "SELECT SUM(x) FROM n"
        ).scalar() == 50_005_000


@pytest.mark.parametrize("failure", ["timeout", "progress", "rollback"])
def test_failed_cleanup_invalidates_connection(database, failure):
    engine, repository = database
    with pytest.raises(QueryError) as raised:
        with repository.session(PathBudget(1000, 100)) as reader:
            raw = reader.connection.connection.driver_connection
            raw.fail_cleanup = failure
    assert raised.value.code == "STORAGE_UNAVAILABLE"
    assert engine.pool.checkedout() == 0
    with engine.connect() as connection:
        assert connection.connection.driver_connection is not raw
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1


def test_already_invalidated_connection_is_not_restored(database):
    engine, repository = database
    with repository.session(PathBudget(1000, 100)) as reader:
        raw = reader.connection.connection.driver_connection
        reader.connection.invalidate()
    with engine.connect() as connection:
        assert connection.connection.driver_connection is not raw
    assert engine.pool.checkedout() == 0
