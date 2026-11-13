"""只读图会话边界：每次 RPC 使用剩余预算、独立回收 SDK 连接。"""

import logging
from hashlib import sha256
from math import ceil
from threading import BoundedSemaphore
from typing import Any

from nebula3.Config import Config  # type: ignore[import-untyped]
from nebula3.Exception import (  # type: ignore[import-untyped]
    AuthFailedException,
    ClientServerIncompatibleException,
    IOErrorException,
    NotValidConnectionException,
    NoValidSessionException,
)
from nebula3.gclient.net import ConnectionPool  # type: ignore[import-untyped]

from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.graph_model import (
    ProjectionManifest,
    ReaderCredentials,
    literal,
)
from relationship_query.infrastructure.source_graph_model import SourceManifest
from relationship_query.runtime.diagnostics import traced
from relationship_query.services.query import QueryError

logger = logging.getLogger("relationship_query.graph")


class GraphDependencyError(QueryError):
    def __init__(self, native_code: int | None = None) -> None:
        self.native_code = native_code
        super().__init__("GRAPH_UNAVAILABLE", "图查询服务暂不可用，请稍后重试", 503)


class GraphClient:
    def __init__(
        self, manifest: ProjectionManifest | SourceManifest, credentials: ReaderCredentials
    ) -> None:
        self.manifest, self.credentials = manifest, credentials
        self.slots = BoundedSemaphore(4)

    @traced("GraphClient.execute")
    def execute(
        self, statement: str, budget: PathBudget, maximum_rows: int
    ) -> list[dict[str, Any]]:
        budget.graph_request(maximum_rows)
        if not self.slots.acquire(timeout=max(0, min(0.1, budget.deadline - budget.clock()))):
            budget.check()
            raise QueryError("GRAPH_BUSY", "图查询连接已满，请稍后重试", 503)
        pool, session = ConnectionPool(), None
        try:
            config = Config()
            config.timeout = max(1, ceil((budget.deadline - budget.clock()) * 1000))
            config.max_connection_pool_size = 1
            if not pool.init([(self.credentials.host, self.credentials.port)], config):
                raise GraphDependencyError()
            session = pool.get_session(
                self.credentials.username, self.credentials.password.get_secret_value()
            )
            budget.check()
            result = session.execute(f"USE `{self.manifest.space}`; " + statement)
            if not result.is_succeeded():
                logger.warning(
                    "graph execution rejected code=%s detail=%s statement=%s "
                    "calls=%s rows=%s elapsed_ms=%s",
                    result.error_code(),
                    str(result.error_msg())[:512],
                    sha256(statement.encode()).hexdigest()[:16],
                    budget.graph_calls,
                    budget.graph_rows,
                    budget.elapsed_ms(),
                )
                raise GraphDependencyError(result.error_code())
            rows = list(result.as_primitive())
            if len(rows) > maximum_rows:
                raise QueryError("GRAPH_INTEGRITY", "图投影超出已验证的读取边界", 503)
            budget.graph_result(len(rows))
            return rows
        except IOErrorException as exc:
            if exc.type == IOErrorException.E_TIMEOUT:
                raise PathBudgetExceeded("time_limit") from None
            raise GraphDependencyError() from None
        except (
            AuthFailedException,
            ClientServerIncompatibleException,
            NotValidConnectionException,
            NoValidSessionException,
            OSError,
            RuntimeError,
        ) as exc:
            logger.warning("graph dependency failure: %s", type(exc).__name__)
            budget.check()
            raise GraphDependencyError() from None
        finally:
            if session is not None:
                session.release()
            pool.close()
            self.slots.release()

    def check_version(self, budget: PathBudget) -> None:
        rows = self.execute(
            'FETCH PROP ON projection "meta|projection" YIELD properties(vertex) AS meta', budget, 1
        )
        expected = {
            "status": "ready",
            "projection_id": self.manifest.projection_id,
            "source_digest": self.manifest.source_digest,
            "data_version": self.manifest.data_version,
            "reference_month": self.manifest.reference_month,
            "format_version": 1,
        }
        if len(rows) != 1 or rows[0]["meta"] != expected:
            raise QueryError("GRAPH_VERSION_MISMATCH", "图投影批次未完成或已变化，请重新接入", 409)

    def fetch(self, tag: str, ids: list[str], budget: PathBudget) -> dict[str, dict[str, Any]]:
        if tag not in {"person", "entity", "roster"} or not 1 <= len(ids) <= 64:
            raise ValueError("图读取类型或批次无效")
        rows = self.execute(
            f"FETCH PROP ON {tag} "
            + ",".join(literal(i) for i in ids)
            + " YIELD id(vertex) AS vid, properties(vertex) AS properties",
            budget,
            len(ids),
        )
        result = {row["vid"]: row["properties"] for row in rows}
        if set(result) != set(ids):
            raise QueryError("GRAPH_INTEGRITY", "图投影缺少已发布记录", 503)
        return result
