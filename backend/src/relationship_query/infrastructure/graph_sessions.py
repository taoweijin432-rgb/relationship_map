"""固定SDK版本的有界独占会话；超时连接丢弃，避免残留响应串入下一请求。"""

import logging
from math import ceil
from threading import Lock
from time import monotonic
from typing import Any

from nebula3.data.ResultSet import ResultSet  # type: ignore[import-untyped]
from nebula3.Exception import (  # type: ignore[import-untyped]
    ClientServerIncompatibleException,
    IOErrorException,
)
from nebula3.fbthrift.transport.TTransport import (  # type: ignore[import-untyped]
    TTransportException,
)
from nebula3.gclient.net.Connection import Connection  # type: ignore[import-untyped]

from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.graph_model import ReaderCredentials
from relationship_query.runtime.diagnostics import observe

logger = logging.getLogger("relationship_query.graph")
# 当前图服务8小时关闭空闲连接；借用前提前回收，避免隔夜首个请求使用已断开的流。
MAX_IDLE_SECONDS = 300.0


def remaining_ms(budget: PathBudget) -> int:
    budget.check()
    return max(1, ceil((budget.deadline - budget.clock()) * 1000))


class DeadlineConnection(Connection):  # type: ignore[misc]
    def _reopen(self) -> None:
        # SDK默认超时后再次连接，可能把一次剩余预算消耗两次；由下次借用补建。
        self.close()

    def set_timeout(self, milliseconds: int) -> None:
        self._timeout = milliseconds
        # nebula3-python==3.8.3的Thrift TCP transport，集中封装SDK内部访问。
        self._connection._iprot.trans.getTransport().getTransport().setTimeout(milliseconds)


class GraphSession:
    def __init__(self, credentials: ReaderCredentials, budget: PathBudget) -> None:
        self.credentials = credentials
        self.connection = DeadlineConnection()
        self.auth: Any = None
        try:
            self.connection.open(credentials.host, credentials.port, remaining_ms(budget))
            self.connection.set_timeout(remaining_ms(budget))
            self.auth = self.connection.authenticate(
                credentials.username, credentials.password.get_secret_value()
            )
            budget.check()
        except BaseException:
            if self.auth is not None:
                self.release()
            else:
                self.connection.close()
            raise

    def execute(self, statement: str, budget: PathBudget) -> Any:
        self.connection.set_timeout(remaining_ms(budget))
        response = self.connection.execute_parameter(self.auth.get_session_id(), statement, None)
        return ResultSet(response, all_latency=0, timezone_offset=self.auth.get_timezone_offset())

    def close(self) -> None:
        self.connection.close()

    def discard(self) -> None:
        # 残留响应的旧流不可复用；另开短连接注销自己的会话，停止可能仍在执行的查询。
        self.close()
        cleanup = DeadlineConnection()
        deadline = monotonic() + 0.2
        try:
            cleanup.open(self.credentials.host, self.credentials.port, 200)
            if monotonic() < deadline:
                cleanup.set_timeout(max(1, int((deadline - monotonic()) * 1000)))
                cleanup.signout(self.auth.get_session_id())
        except (
            IOErrorException,
            TTransportException,
            ClientServerIncompatibleException,
            OSError,
            RuntimeError,
        ) as error:
            logger.warning("graph session discard cleanup failed: %s", type(error).__name__)
        finally:
            cleanup.close()

    def release(self) -> None:
        try:
            self.connection.set_timeout(200)
            self.connection.signout(self.auth.get_session_id())
        except (IOErrorException, TTransportException, OSError) as error:
            logger.warning("graph session release failed: %s", type(error).__name__)
        finally:
            self.close()


class GraphSessionPool:
    def __init__(self, credentials: ReaderCredentials) -> None:
        self.credentials = credentials
        self._idle: list[tuple[GraphSession, float]] = []
        self._state = Lock()
        self._creation = Lock()
        self._closed = False

    def borrow(self, budget: PathBudget) -> GraphSession:
        session = self._take_idle(budget)
        if session is not None:
            return session
        # GraphClient的4个名额同时覆盖借用、创建和执行，创建锁不会额外扩张容量。
        if not self._creation.acquire(timeout=max(0, budget.deadline - budget.clock())):
            budget.check()
            raise RuntimeError("Graph session creation timed out")
        try:
            session = self._take_idle(budget)
            if session is not None:
                return session
            session = GraphSession(self.credentials, budget)
            with self._state:
                if self._closed:
                    session.release()
                    raise RuntimeError("Graph session pool is closed")
            return session
        finally:
            self._creation.release()

    def _take_idle(self, budget: PathBudget) -> GraphSession | None:
        while True:
            budget.check()
            with self._state:
                if self._closed:
                    raise RuntimeError("Graph session pool is closed")
                if not self._idle:
                    return None
                session, returned_at = self._idle.pop()
            if monotonic() - returned_at < MAX_IDLE_SECONDS:
                return session
            # 注销有独立的短I/O超时，不持状态锁；下轮先检查预算，不能重开请求截止时间。
            session.release()
            observe("graph.session_idle_retired")

    def give_back(self, session: GraphSession, *, reusable: bool) -> None:
        with self._state:
            if reusable and not self._closed:
                self._idle.append((session, monotonic()))
                return
        if reusable:
            session.release()
        else:
            session.discard()

    def close(self) -> None:
        with self._state:
            self._closed = True
            idle, self._idle = self._idle, []
        for session, _ in idle:
            session.release()
