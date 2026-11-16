import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.read_model import QueryTables, dataset_meta
from relationship_query.infrastructure.sql_paths import SQLPathReader
from relationship_query.services.ports import PathReader
from relationship_query.services.query import QueryError


class SQLitePathRepository:
    def __init__(
        self,
        engine: Engine,
        version: str,
        reference_month: int,
        *,
        tables: QueryTables | None = None,
    ) -> None:
        self.engine, self.version, self.reference_month = engine, version, reference_month
        self.tables = tables

    @contextmanager
    def session(self, budget: PathBudget) -> Iterator[PathReader]:
        budget.check()
        with self.engine.connect() as connection:
            raw = cast(sqlite3.Connection, connection.connection.driver_connection)
            original_timeout = int(raw.execute("PRAGMA busy_timeout").fetchone()[0])
            # 处理器只在当前借用连接上生效，退出后清除，防止影响普通查询。
            raw.set_progress_handler(budget.progress, 1000)
            try:
                budget.check()
                raw.execute(
                    f"PRAGMA busy_timeout={max(1, int((budget.deadline - budget.clock()) * 1000))}"
                )
                connection.exec_driver_sql("BEGIN")
                current = connection.execute(select(dataset_meta)).one()
                if (
                    current.version != self.version
                    or current.reference_month != self.reference_month
                ):
                    raise QueryError(
                        "DATA_VERSION_CHANGED", "数据批次已变化，请停止并重新启动服务", 409
                    )
                yield self._reader(connection, budget)
            except OperationalError as exc:
                if budget.interrupted:
                    raise PathBudgetExceeded(budget.interrupted) from exc
                budget.check()
                raise
            finally:
                self._restore_connection(connection, raw, original_timeout)

    @staticmethod
    def _restore_connection(
        connection: Connection, raw: sqlite3.Connection, original_timeout: int
    ) -> None:
        if connection.invalidated:
            return
        try:
            raw.set_progress_handler(None, 0)
            connection.rollback()
            raw.execute(f"PRAGMA busy_timeout={original_timeout}")
        except (sqlite3.Error, SQLAlchemyError) as error:
            # rollback不会重置连接级PRAGMA；清理失败的连接不能重新进入池。
            connection.invalidate(error)
            raise QueryError("STORAGE_UNAVAILABLE", "查询连接恢复失败，请稍后重试", 503) from error

    def _reader(self, connection: Connection, budget: PathBudget) -> "SQLitePathReader":
        return SQLitePathReader(connection, budget, self.reference_month, self.tables)


class SQLitePathReader(SQLPathReader):
    pass
