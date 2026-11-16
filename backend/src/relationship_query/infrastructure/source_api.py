"""显式启用的原表／三表集成模式；SQL 只读，图内计算有界连接链。"""

import json
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from sqlalchemy.engine import Connection, Engine

from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.graph_client import GraphClient
from relationship_query.infrastructure.graph_model import read_reader
from relationship_query.infrastructure.graph_relation_queries import SOURCE_SLOT_MODEL
from relationship_query.infrastructure.graph_relations import NativeGraphReader
from relationship_query.infrastructure.mysql import (
    MySQLPathRepository,
    open_remote_mysql_engine,
    source_url,
)
from relationship_query.infrastructure.projection_source_trial import (
    configure_projection_engine,
    open_projection_engine,
    projection_records,
)
from relationship_query.infrastructure.source_graph_model import SourceManifest
from relationship_query.infrastructure.source_read_model import (
    query_tables,
    reflect_source,
    snapshot,
    source_digest,
)
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.services.ports import GraphRelationReader, PathReader
from relationship_query.services.query import QueryError


class SourceRepository(SQLRepository):
    def __init__(
        self,
        engine: Engine,
        manifest: SourceManifest,
        *,
        release_check: Callable[[], None] | None = None,
    ) -> None:
        if engine.url.database != manifest.source_database:
            raise QueryError("SOURCE_VERSION_MISMATCH", "配置的原表库与清单不一致", 409)
        self.manifest = manifest
        self.release_check = release_check
        self.source_schema = reflect_source(engine)
        with engine.connect() as connection:
            data = snapshot(connection, self.source_schema)
            self._check_digest(data)
            projection_records(data)
        super().__init__(
            engine,
            tables=query_tables(self.source_schema),
            version=manifest.data_version,
            reference_month=manifest.reference_month,
        )
        self.storage = "mysql-source-slots"

    def _check_digest(self, data: dict) -> None:
        if source_digest(data) != self.manifest.source_digest:
            raise QueryError(
                "SOURCE_VERSION_MISMATCH", "原表快照已变化，请停止服务并重新发布成对快照", 409
            )

    def verify_connection(self, connection: Connection) -> None:
        self._check_digest(snapshot(connection, self.source_schema))

    def verify_snapshot(self) -> None:
        if self.release_check:
            self.release_check()
        with self.engine.connect() as connection:
            self.verify_connection(connection)
        if self.release_check:
            self.release_check()


class SourceGraphClient(GraphClient):
    def check_version(self, budget: PathBudget) -> None:
        rows = self.execute(
            'FETCH PROP ON lab_projection "meta|projection" YIELD properties(vertex) AS meta',
            budget,
            1,
        )
        if len(rows) != 1 or rows[0]["meta"] != {
            "status": "ready",
            "digest": self.manifest.source_digest,
        }:
            raise QueryError("GRAPH_VERSION_MISMATCH", "原表图投影未完成或与 SQL 快照不一致", 409)


class SourceGraphRepository:
    def __init__(self, sql: SourceRepository, manifest_path: Path) -> None:
        self.source, self.manifest = sql, sql.manifest
        self.version, self.reference_month = sql.version, sql.reference_month
        self.sql = MySQLPathRepository(
            sql.engine,
            sql.version,
            sql.reference_month,
            tables=sql.tables,
            verify=sql.verify_connection,
        )
        self.client = SourceGraphClient(self.manifest, read_reader(manifest_path))
        try:
            self.client.check_version(PathBudget(3000, 5000))
        except BaseException:
            self.client.close()
            raise

    def session(self, budget: PathBudget) -> AbstractContextManager[PathReader]:
        return self.sql.session(budget)

    @contextmanager
    def graph_session(self, budget: PathBudget) -> Iterator[GraphRelationReader]:
        with self.sql.session(budget) as reader:
            self.client.check_version(budget)
            yield NativeGraphReader(
                reader, self.client, budget, self.reference_month, SOURCE_SLOT_MODEL
            )
            self.client.check_version(budget)


def read_source_manifest(path: Path) -> SourceManifest:
    from relationship_query.infrastructure.uuid_source import UUIDManifest

    data = json.loads(path.read_text())
    model = UUIDManifest if data.get("format_version") in (3, 4, 5) else SourceManifest
    return model.model_validate(data)


def validate_source_mysql_url(value: str, manifest: SourceManifest) -> None:
    from relationship_query.infrastructure.uuid_source import UUIDManifest

    endpoint = manifest.source_endpoint if isinstance(manifest, UUIDManifest) else None
    source_url(value, manifest.source_database, endpoint)


def open_source_engine(value: str, manifest: SourceManifest, path: Path) -> Engine:
    from relationship_query.infrastructure.uuid_source import UUIDManifest

    validate_source_mysql_url(value, manifest)
    if isinstance(manifest, UUIDManifest) and manifest.source_endpoint is not None:
        engine = open_remote_mysql_engine(
            value, manifest.source_endpoint, path.parent / "mysql-ca.pem"
        )
        configure_projection_engine(engine)
        return engine
    return open_projection_engine(value)
