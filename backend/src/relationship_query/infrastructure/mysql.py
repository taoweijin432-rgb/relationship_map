"""本机实验连接与发布清单绑定的远程只读 MySQL 连接。"""

import hashlib
import re
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pymysql  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymysql.constants import CLIENT  # type: ignore[import-untyped]
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import URL, Connection, Engine, make_url
from sqlalchemy.exc import OperationalError

from relationship_query.contracts import PathRequest
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded, using_budget
from relationship_query.infrastructure.read_model import QueryTables, dataset_meta
from relationship_query.infrastructure.sql_deadlines import DeadlineQueuePool, install_sql_deadlines
from relationship_query.infrastructure.sql_paths import SQLPathReader
from relationship_query.services.ports import PathReader
from relationship_query.services.query import QueryError

LAB_DATABASE = re.compile(r"relationship_lab_[a-z0-9_]{1,48}\Z")
SOURCE_DATABASE = re.compile(r"[A-Za-z0-9_]{1,64}\Z")


class TLSConnection(pymysql.connections.Connection):
    def _request_authentication(self) -> Any:
        if not self.server_capabilities & CLIENT.SSL:
            raise pymysql.OperationalError(2026, "来源MySQL需要TLS连接")
        return super()._request_authentication()


class RemoteMySQL(BaseModel):
    """发布清单绑定远程端点；凭据仍只保存在私有 api.env。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    host: str = Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9:.\-]+$")
    port: int = Field(ge=1, le=65535)
    ca_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    connect_timeout: int = Field(default=3, ge=1, le=30)
    read_timeout: int = Field(default=5, ge=1, le=60)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        return value.lower()


def source_url(value: str, database: str, remote: RemoteMySQL | None = None) -> URL:
    if remote is None:
        url = lab_url(value)
    else:
        url = make_url(value)
        if (
            url.drivername != "mysql+pymysql"
            or (url.host or "").lower() != remote.host
            or (url.port or 3306) != remote.port
            or not url.username
            or not url.password
            or set(url.query) - {"charset"}
            or url.query.get("charset", "utf8mb4") != "utf8mb4"
        ):
            raise ValueError("MySQL 连接必须与发布端点一致，且只允许 utf8mb4 参数")
    if url.database != database:
        raise ValueError("MySQL 连接数据库与发布清单不一致")
    return url


def lab_url(value: str) -> URL:
    url = make_url(value)
    if (
        url.drivername != "mysql+pymysql"
        or url.host not in {"localhost", "127.0.0.1"}
        or not LAB_DATABASE.fullmatch(url.database or "")
        or set(url.query) - {"charset"}
        or url.query.get("charset", "utf8mb4") != "utf8mb4"
    ):
        raise ValueError("MySQL 验证仅接受本机 mysql+pymysql 和 relationship_lab_ 前缀实验库")
    return url


def open_mysql_engine(value: str, *, writable: bool = False) -> Engine:
    return _open_mysql_engine(lab_url(value), writable=writable)


def open_remote_mysql_engine(value: str, remote: RemoteMySQL, ca_file: Path) -> Engine:
    url = source_url(value, make_url(value).database or "", remote)
    ca_data = ca_file.read_bytes()
    if hashlib.sha256(ca_data).hexdigest() != remote.ca_sha256:
        raise ValueError("MySQL CA 证书与发布清单不一致")
    context = ssl.create_default_context(cadata=ca_data.decode("ascii"))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return _open_mysql_engine(
        url,
        writable=False,
        connect_args={
            "ssl": context,
            "connect_timeout": remote.connect_timeout,
            "read_timeout": remote.read_timeout,
        },
    )


def _open_mysql_engine(
    url: URL,
    *,
    writable: bool,
    connect_args: dict[str, Any] | None = None,
    connect_factory: Callable[..., Any] | None = None,
) -> Engine:
    engine = create_engine(
        url,
        pool_size=5,
        max_overflow=0,
        pool_timeout=3,
        pool_recycle=1800,
        pool_pre_ping=True,
        isolation_level="REPEATABLE READ",
        connect_args={
            "charset": "utf8mb4",
            "connect_timeout": 3,
            "read_timeout": 5,
            "write_timeout": 5,
            **(connect_args or {}),
        },
        hide_parameters=True,
        poolclass=DeadlineQueuePool,
    )
    install_sql_deadlines(engine, mysql_connect=connect_factory)

    @event.listens_for(engine, "connect")
    def configure(connection: Any, _record: Any) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION max_execution_time = 3000")
            cursor.execute("SET SESSION innodb_lock_wait_timeout = 3")
            if not writable:
                cursor.execute("SET SESSION transaction_read_only = 1")

    return engine


def mysql_path_timeout(error: OperationalError) -> bool:
    # 仅服务端已确认的语句执行超时转换为预算结果；断连和锁等待保持服务错误。
    return bool(error.orig is not None and error.orig.args and error.orig.args[0] == 3024)


class MySQLPathRepository:
    def __init__(
        self,
        engine: Engine,
        version: str,
        reference_month: int,
        *,
        tables: QueryTables | None = None,
        verify: Callable[[Connection], None] | None = None,
    ) -> None:
        self.engine, self.version, self.reference_month = engine, version, reference_month
        self.tables, self.verify = tables, verify

    @contextmanager
    def session(self, budget: PathBudget) -> Iterator[PathReader]:
        budget.check()
        with using_budget(budget), self.engine.connect() as connection:
            try:
                if self.verify:
                    self.verify(connection)
                else:
                    current = connection.execute(select(dataset_meta)).one()
                    if (current.version, current.reference_month) != (
                        self.version,
                        self.reference_month,
                    ):
                        raise QueryError("DATA_VERSION_CHANGED", "数据批次已变化，请重启服务", 409)
                yield MySQLPathReader(connection, budget, self.reference_month, self.tables)
                budget.check()
            except OperationalError as exc:
                if mysql_path_timeout(exc):
                    raise PathBudgetExceeded("time_limit") from exc
                raise
            finally:
                connection.rollback()


class MySQLPathReader(SQLPathReader):
    def candidates(self, request: PathRequest) -> list[str]:
        if self._broad_anchor(request):
            return self._ordered_candidates(request, stop_at_first=True)
        return self._joined_candidates(request)
