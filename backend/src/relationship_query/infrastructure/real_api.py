"""真实图构建产物的只读查询入口，启动全量校验后固定成对SQL和图。"""

import json
from pathlib import Path
from time import monotonic
from typing import Literal

from nebula3.Config import Config  # type: ignore[import-untyped]
from nebula3.gclient.net import ConnectionPool  # type: ignore[import-untyped]

from relationship_query.infrastructure.graph_model import ReaderCredentials, read_reader
from relationship_query.infrastructure.nebula_lab import query
from relationship_query.infrastructure.numeric_api import NumericGraphClient, NumericRepository
from relationship_query.infrastructure.uuid_projection import graph_digest, read_all
from relationship_query.services.query import QueryError
from relationship_query.update.artifacts import checksum
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import GraphReceipt, UpdateModel, digest


class RealGraphBuild(UpdateModel):
    format: Literal["real-graph-build-v1"]
    data_mode: Literal["real"]
    state: Literal["verified"]
    version: str
    source_digest: str
    reference_month: int
    sources: list[dict]
    graph: GraphReceipt
    validation: dict
    elapsed_seconds: float
    person_display: Literal["snapshot", "mysql-live"] = "snapshot"


def file_signature(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class RealGraphRepository(NumericRepository):
    data_mode = "real"

    def __init__(self, directory: Path) -> None:
        self.directory = self.release = directory.resolve()
        names = (
            "contract.json",
            "source-snapshot.json",
            "input-audit.json",
            "source.sqlite",
            "graph-plan.json",
            "manifest.json",
            "prepared.json",
            "graph-receipt.json",
            "graph/build-resource.json",
            "graph/reader-credentials.json",
        )
        self._signatures = {
            self.release / name: file_signature(self.release / name) for name in names
        }
        self.real_build = RealGraphBuild.model_validate_json(
            (self.release / "manifest.json").read_text()
        )
        prepared = json.loads((self.release / "prepared.json").read_text())
        self._validate_prepared(prepared)
        self.contract_file = self.release / "contract.json"
        self.contract = SourceContract.model_validate_json(self.contract_file.read_text())
        self.verify_snapshot()
        self._open_read_model(
            self.real_build.version,
            self.real_build.source_digest,
            self.real_build.reference_month,
            self.real_build.graph,
        )
        try:
            expected = (sum(prepared["nodes"].values()), sum(prepared["facts"].values()))
            if expected != (self.real_build.graph.node_count, self.real_build.graph.fact_count):
                raise ValueError("真实图节点／事实计数与已准备输入不符")
            counts = self.counts()
            if (counts["person_count"] + counts["entity_count"], counts["fact_count"]) != expected:
                raise ValueError("真实查询SQL计数与图不符")
            self.verify_snapshot()
        except Exception:
            self.engine.dispose()
            raise

    def _validate_prepared(self, prepared: dict) -> None:
        required = {
            "contract.json",
            "source-snapshot.json",
            "input-audit.json",
            "source.sqlite",
            "graph-plan.json",
        }
        if prepared.get("format") != "real-graph-plan-v1" or set(prepared["files"]) != required:
            raise ValueError("真实图准备清单不完整")
        for name, expected in prepared["files"].items():
            if checksum(self.release / name) != expected:
                raise ValueError("真实查询发布文件摘要不符")
        for key in ("version", "source_digest", "reference_month", "sources", "data_mode"):
            if prepared[key] != getattr(self.real_build, key):
                raise ValueError("真实图清单与已准备输入不匹配")
        rows = json.loads((self.release / "source-snapshot.json").read_text())
        if digest(rows) != self.real_build.source_digest:
            raise ValueError("真实来源规范化快照摘要不符")
        receipt = GraphReceipt.model_validate_json(
            (self.release / "graph-receipt.json").read_text()
        )
        if receipt != self.real_build.graph or receipt.backend != "nebula":
            raise ValueError("真实图收据不匹配")
        proofs = self.real_build.validation.get("independent_sql_proofs", {})
        if self.real_build.validation.get("passed") is not True or set(proofs) != {
            "same_company",
            "company_overlap",
            "same_school",
            "same_major",
        }:
            raise ValueError("真实图需要完整的独立SQL核对结果")
        if sum(proof["count"] for proof in proofs.values()) != receipt.relation_count:
            raise ValueError("真实人物关系证据计数不符")

    def verify_snapshot(self) -> None:
        try:
            if any(file_signature(path) != expected for path, expected in self._signatures.items()):
                raise ValueError("真实发布文件发生变化")
        except (OSError, ValueError):
            raise QueryError(
                "SOURCE_VERSION_MISMATCH", "真实数据发布已变化，请重新载入服务", 409
            ) from None

    def _graph_credentials(self) -> ReaderCredentials:
        return read_reader(self.release / "graph/build-resource.json")

    def _verify_graph(self, client: NumericGraphClient, plan: dict) -> None:
        # 发布核对拥有独立启动预算，业务查询继续使用既有请求预算。
        deadline = monotonic() + 120
        config = Config()
        config.timeout, config.max_connection_pool_size = 15000, 1
        pool, session = ConnectionPool(), None
        bound = max(self.real_build.graph.fact_count + self.real_build.graph.relation_count, 1)
        try:
            if not pool.init([(client.credentials.host, client.credentials.port)], config):
                raise QueryError("GRAPH_UNAVAILABLE", "真实图只读连接未就绪", 503)
            session = pool.get_session(
                client.credentials.username, client.credentials.password.get_secret_value()
            )
            query(session, f"USE `{self.manifest.space}`")

            def execute(statement: str, maximum: int) -> list[dict]:
                if monotonic() >= deadline:
                    raise QueryError("GRAPH_QUERY_LIMIT", "真实图启动完整核对达到时间预算", 503)
                records = query(session, statement)
                if len(records) > maximum:
                    raise QueryError("GRAPH_INTEGRITY", "真实图回读超出计划范围", 503)
                return records

            nodes, edges = read_all(execute, plan["nodes"], max_rows_per_query=bound)
            if graph_digest(nodes, edges) != self.real_build.graph.graph_digest:
                raise QueryError("GRAPH_INTEGRITY", "真实图完整回读摘要不符", 503)
        finally:
            if session is not None:
                session.release()
            pool.close()
