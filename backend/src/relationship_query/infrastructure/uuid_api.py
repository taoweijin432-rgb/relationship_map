"""新 UUID 冻结源的只读仓储；SQL 筛背景，图提供人物关联集合。"""

from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import Connection, Engine

from relationship_query.infrastructure.materialized_sql import MaterializedSQLRepository
from relationship_query.infrastructure.source_read_model import snapshot, source_digest
from relationship_query.infrastructure.uuid_source import (
    NAMES,
    UUIDManifest,
    projection_records,
    query_tables,
    reflect,
)
from relationship_query.services.query import QueryError


class UUIDRepository(MaterializedSQLRepository):
    def __init__(
        self,
        engine: Engine,
        manifest: UUIDManifest,
        *,
        release_check: Callable[[], None] | None = None,
    ) -> None:
        if engine.url.database != manifest.source_database:
            raise QueryError("SOURCE_VERSION_MISMATCH", "UUID 来源库与清单不一致", 409)
        self.manifest, self.release_check = manifest, release_check
        self.source_schema = reflect(engine)
        with engine.connect() as connection:
            data = snapshot(connection, self.source_schema, NAMES)
            self._check(data)
            projection_records(data, manifest.reference_month)
            if manifest.sql_guard:
                from relationship_query.infrastructure.sql_release_guard import (
                    verify,
                    verify_reader,
                )

                if manifest.source_endpoint is None and not (engine.url.username or "").startswith(
                    "rqsql_"
                ):
                    raise ValueError("轻量校验只允许发布工具创建的 SQL 只读账号")
                verify_reader(connection, manifest)
                verify(connection, manifest)
        super().__init__(
            engine,
            tables=query_tables(self.source_schema),
            version=manifest.data_version,
            reference_month=manifest.reference_month,
        )
        self.storage = "mysql-uuid-source"
        self.graph: Any = None

    def _check(self, data: dict) -> None:
        if source_digest(data) != self.manifest.source_digest:
            raise QueryError("SOURCE_VERSION_MISMATCH", "UUID 来源快照已变化，请停服重新发布", 409)

    def verify_connection(self, connection: Connection) -> None:
        if self.manifest.sql_guard:
            from relationship_query.infrastructure.sql_release_guard import verify

            verify(connection, self.manifest)
            return
        self._check(snapshot(connection, self.source_schema, NAMES))

    def verify_snapshot(self) -> None:
        if self.release_check:
            self.release_check()
        with self.engine.connect() as connection:
            self.verify_connection(connection)
        if self.release_check:
            self.release_check()
