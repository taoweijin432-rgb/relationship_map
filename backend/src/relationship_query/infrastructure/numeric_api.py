"""数字更新发布的只读HTTP查询适配，复用SQL筛选及图中物化人物关系。"""

import json
from pathlib import Path
from typing import Literal, cast

from sqlalchemy import create_engine, exists, select
from sqlalchemy.sql.elements import ColumnElement

from relationship_query.contracts import SearchRequest
from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.graph_model import (
    ProjectionManifest,
    ReaderCredentials,
    read_reader,
)
from relationship_query.infrastructure.materialized_sql import MaterializedSQLRepository
from relationship_query.infrastructure.numeric_read_model import query_schema
from relationship_query.infrastructure.sql_deadlines import DeadlineQueuePool, install_sql_deadlines
from relationship_query.infrastructure.sqlite_paths import SQLitePathRepository
from relationship_query.infrastructure.uuid_graph import (
    MaterializedGraphRepository,
    UUIDGraphClient,
)
from relationship_query.infrastructure.uuid_projection import graph_digest, read_all
from relationship_query.services.query import QueryError
from relationship_query.update.artifacts import artifact_directory, checksum, load_active
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import GraphReceipt, UpdateError


class NumericManifest(ProjectionManifest):
    model: Literal["numeric-relations-v1"] = "numeric-relations-v1"


class NumericGraphClient(UUIDGraphClient):
    def check_version(self, budget: PathBudget) -> None:
        rows = self.execute(
            'FETCH PROP ON projection_meta "meta:projection" YIELD properties(vertex) AS meta',
            budget,
            1,
        )
        expected = {
            "schema_version": "numeric-relations-v1",
            "projection_id": self.manifest.projection_id,
            "snapshot_sha256": self.manifest.source_digest,
            "reference_month": self.manifest.reference_month,
            "state": "ready",
        }
        if rows != [{"meta": expected}]:
            raise QueryError("GRAPH_VERSION_MISMATCH", "图与数字SQL发布版本不匹配", 409)


class NumericRepository(MaterializedSQLRepository):
    def _filter_conditions(self, request: SearchRequest) -> list[ColumnElement[bool]]:
        if not request.school_ids or not request.major_ids:
            return super()._filter_conditions(request)
        conditions = super()._filter_conditions(
            request.model_copy(update={"school_ids": [], "major_ids": []})
        )
        school, major = (
            self.tables.facts.alias("school_fact"),
            self.tables.facts.alias("major_fact"),
        )
        conditions.append(
            exists(
                select(school.c.id)
                .join(
                    major,
                    (school.c.person_id == major.c.person_id)
                    & (school.c.experience_key == major.c.experience_key),
                )
                .where(
                    school.c.person_id == self.tables.people.c.id,
                    school.c.active.is_(True),
                    major.c.active.is_(True),
                    school.c.type == "education",
                    major.c.type == "major",
                    school.c.entity_id.in_(request.school_ids),
                    major.c.entity_id.in_(request.major_ids),
                )
            )
        )
        return conditions

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.contract_file = self.directory.parent / "contract.json"
        self.contract = SourceContract.model_validate_json(self.contract_file.read_text())
        self.contract_hash = checksum(self.contract_file)
        selected = load_active(self.directory, self.contract)
        if selected is None or selected[1].graph is None or selected[1].graph.backend != "nebula":
            raise ValueError("数字查询需要已核对的原生图发布")
        self.pointer, self.build = selected
        self.release = artifact_directory(self.directory, self.build.batch_id, self.build.token)
        self._open_read_model(
            self.build.version,
            self.build.source_digest,
            self.build.reference_month,
            selected[1].graph,
        )

    def _open_read_model(
        self, version: str, source_digest: str, reference_month: int, graph: GraphReceipt
    ) -> None:
        self._graph_receipt = graph
        engine = create_engine(
            f"sqlite:///file:{self.release / 'source.sqlite'}?mode=ro&uri=true",
            connect_args={"check_same_thread": False},
            poolclass=DeadlineQueuePool,
            hide_parameters=True,
        )
        install_sql_deadlines(engine)
        schema, tables = query_schema()
        try:
            with engine.connect() as connection:
                marker = (
                    connection.execute(select(schema.tables["numeric_query_meta"])).mappings().one()
                )
                dataset = connection.execute(select(schema.tables["demo_dataset"])).one()
                if (
                    marker["format_version"],
                    marker["contract_digest"],
                    marker["source_digest"],
                    dataset.version,
                    dataset.reference_month,
                ) != (
                    1,
                    self.contract.fingerprint,
                    source_digest,
                    version,
                    reference_month,
                ):
                    raise ValueError("数字查询SQL读模型与发布清单不一致")
            super().__init__(
                engine,
                tables=tables,
                version=version,
                reference_month=reference_month,
            )
            self.manifest = NumericManifest(
                space=graph.space,
                projection_id=version,
                data_version=version,
                reference_month=reference_month,
                source_digest=source_digest,
                counts=cast(dict[str, int], self.counts()),
            )
            self.storage = "sqlite-numeric-source"
            self.graph = None
        except Exception:
            engine.dispose()
            raise

    def verify_snapshot(self) -> None:
        try:
            current = load_active(self.directory, self.contract)
            if checksum(self.contract_file) != self.contract_hash or current != (
                self.pointer,
                self.build,
            ):
                raise ValueError("release changed")
        except (OSError, ValueError, UpdateError):
            raise QueryError(
                "SOURCE_VERSION_MISMATCH", "数字来源发布已变化，请刷新服务版本", 409
            ) from None

    def graph_repository(self) -> MaterializedGraphRepository:
        paths = SQLitePathRepository(
            self.engine, self.version, self.reference_month, tables=self.tables
        )
        client = NumericGraphClient(self.manifest, self._graph_credentials())
        try:
            graph = MaterializedGraphRepository(self, paths, client)
            plan = json.loads((self.release / "graph-plan.json").read_text())
            self._verify_graph(client, plan)
            self.verify_snapshot()
            self.graph = graph
            return graph
        except BaseException:
            client.close()
            raise

    def _graph_credentials(self) -> ReaderCredentials:
        return read_reader(self.release / "manifest.json")

    def _verify_graph(self, client: NumericGraphClient, plan: dict) -> None:
        budget = PathBudget(30_000, 20_000)
        nodes, edges = read_all(
            lambda statement, maximum: client.execute(statement, budget, maximum), plan["nodes"]
        )
        if graph_digest(nodes, edges) != self._graph_receipt.graph_digest:
            raise QueryError("GRAPH_INTEGRITY", "数字图完整回读与发布摘要不符", 503)
