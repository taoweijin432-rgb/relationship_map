"""只读图会话边界：有界独占复用，每次RPC遵守剩余预算。"""

import logging
import weakref
from hashlib import sha256
from threading import BoundedSemaphore
from typing import Any

from nebula3.common.ttypes import ErrorCode  # type: ignore[import-untyped]
from nebula3.Exception import (  # type: ignore[import-untyped]
    AuthFailedException,
    ClientServerIncompatibleException,
    IOErrorException,
    NotValidConnectionException,
    NoValidSessionException,
)

from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.graph_model import (
    ProjectionManifest,
    ReaderCredentials,
    literal,
)
from relationship_query.infrastructure.graph_sessions import GraphSession, GraphSessionPool
from relationship_query.infrastructure.source_graph_model import SourceManifest
from relationship_query.runtime.diagnostics import observe, request_id, stage, traced
from relationship_query.runtime.relation_cache import RelationCache
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
        self.sessions = GraphSessionPool(credentials)
        self.relation_cache = RelationCache.configured(
            f"relation-v1/{manifest.space}/{manifest.projection_id}/{manifest.source_digest}"
        )
        self._finalizer = weakref.finalize(self, self.sessions.close)

    def close(self) -> None:
        self.relation_cache.close()
        self._finalizer()

    @traced("GraphClient.execute")
    def execute(
        self, statement: str, budget: PathBudget, maximum_rows: int
    ) -> list[dict[str, Any]]:
        budget.graph_request(maximum_rows)
        with stage("GraphClient.slot_wait"):
            acquired = self.slots.acquire(
                timeout=max(0, min(0.1, budget.deadline - budget.clock()))
            )
        if not acquired:
            observe("graph.slot_rejected")
            budget.check()
            raise QueryError("GRAPH_BUSY", "图查询连接已满，请稍后重试", 503)
        try:
            result = self._session_result(statement, budget, maximum_rows)
            if not result.is_succeeded():
                logger.warning(
                    "graph execution rejected code=%s detail=%s statement=%s "
                    "calls=%s rows=%s elapsed_ms=%s request_id=%s",
                    result.error_code(),
                    str(result.error_msg())[:512],
                    sha256(statement.encode()).hexdigest()[:16],
                    budget.graph_calls,
                    budget.graph_rows,
                    budget.elapsed_ms(),
                    request_id(),
                )
                raise GraphDependencyError(result.error_code())
            rows = list(result.as_primitive())
            if len(rows) > maximum_rows:
                raise QueryError("GRAPH_INTEGRITY", "图投影超出已验证的读取边界", 503)
            budget.graph_result(len(rows))
            observe("graph.rows", len(rows))
            return rows
        except IOErrorException as exc:
            if exc.type == IOErrorException.E_TIMEOUT:
                raise PathBudgetExceeded("time_limit") from None
            logger.warning(
                "graph dependency failure: IOErrorException type=%s statement=%s "
                "elapsed_ms=%s request_id=%s",
                exc.type,
                sha256(statement.encode()).hexdigest()[:16],
                budget.elapsed_ms(),
                request_id(),
            )
            raise GraphDependencyError() from None
        except (
            AuthFailedException,
            ClientServerIncompatibleException,
            NotValidConnectionException,
            NoValidSessionException,
            OSError,
            RuntimeError,
        ) as exc:
            logger.warning(
                "graph dependency failure: %s request_id=%s", type(exc).__name__, request_id()
            )
            budget.check()
            raise GraphDependencyError() from None
        finally:
            self.slots.release()

    def _session_result(self, statement: str, budget: PathBudget, maximum_rows: int) -> Any:
        for attempt in range(2):
            with stage("GraphClient.session_wait"):
                session: GraphSession = self.sessions.borrow(budget)
            reusable = False
            try:
                budget.check()
                observe("graph.rpc")
                result = session.execute(f"USE `{self.manifest.space}`; " + statement, budget)
                reusable = result.error_code() not in {
                    ErrorCode.E_SESSION_INVALID,
                    ErrorCode.E_SESSION_TIMEOUT,
                }
            finally:
                self.sessions.give_back(session, reusable=reusable)
            if reusable or attempt:
                return result
            # 仅会话失效后的只读重试一次，不重试慢查询、资源拒绝或传输超时。
            budget.graph_request(maximum_rows)
        raise AssertionError("Session retry must return or raise")

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
