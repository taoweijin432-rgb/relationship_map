from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event
from time import monotonic
from typing import Literal

PathLimit = Literal[
    "candidate_limit",
    "path_limit",
    "fact_limit",
    "pair_limit",
    "evidence_limit",
    "time_limit",
    "sql_limit",
    "graph_limit",
    "cancelled",
]


class PathBudgetExceeded(Exception):
    def __init__(self, reason: PathLimit) -> None:
        self.reason = reason
        super().__init__(reason)

    @property
    def label(self) -> str:
        return {
            "time_limit": "执行时间",
            "graph_limit": "图读取行数或次数",
            "sql_limit": "SQL执行量",
            "candidate_limit": "候选人物数量",
            "path_limit": "路径数量",
            "fact_limit": "事实数量",
            "pair_limit": "经历配对数量",
            "evidence_limit": "证据数量",
            "cancelled": "请求已取消",
        }.get(self.reason, "查询量")


_request_budget: ContextVar["PathBudget | None"] = ContextVar("relation_query_budget", default=None)


def relation_query_budget() -> "PathBudget":
    return _request_budget.get() or PathBudget(5000, 5000)


def current_query_budget() -> "PathBudget | None":
    """离线构建和启动核验不自动创建交互预算。"""
    return _request_budget.get()


@contextmanager
def using_budget(budget: "PathBudget") -> Iterator["PathBudget"]:
    token = _request_budget.set(budget)
    try:
        yield budget
    finally:
        _request_budget.reset(token)


@contextmanager
def shared_relation_budget() -> Iterator["PathBudget"]:
    budget = relation_query_budget()
    with using_budget(budget):
        yield budget


class PathBudget:
    """请求内预算；SQLite 与 Python 循环共同检查，不能用最终 LIMIT 代替执行预算。"""

    def __init__(
        self,
        time_ms: int,
        fact_limit: int,
        *,
        clock: Callable[[], float] = monotonic,
        sql_limit: int = 500_000,
        pair_limit: int = 50_000,
        inherit_request: bool = True,
    ) -> None:
        self.clock, self.started = clock, clock()
        self.deadline = self.started + time_ms / 1000
        self.parent = _request_budget.get() if inherit_request else None
        if self.parent is not None:
            # 自定义测试时钟与monotonic可能原点不同，只传播剩余时长。
            self.deadline = min(
                self.deadline,
                self.started + max(0, self.parent.deadline - self.parent.clock()),
            )
        self._cancelled: Event = self.parent._cancelled if self.parent else Event()
        self.fact_limit, self.sql_limit, self.pair_limit = fact_limit, sql_limit, pair_limit
        self.facts = self.pairs = self.sql_steps = 0
        self.interrupted: PathLimit | None = None
        self._graph_rows = self._graph_calls = 0
        self.graph_candidates = 0
        self.candidate_reasons: set[PathLimit] = set()

    def graph_request(self, maximum_rows: int) -> None:
        self.check()
        if self.parent is not None:
            self.parent.graph_request(maximum_rows)
            return
        if self.graph_calls >= 256 or self.graph_rows + maximum_rows > 20_000:
            raise PathBudgetExceeded("graph_limit")
        self._graph_calls += 1

    def graph_result(self, rows: int) -> None:
        if self.parent is not None:
            self.parent.graph_result(rows)
        else:
            self._graph_rows += rows
        self.check()

    @property
    def graph_calls(self) -> int:
        return self.parent.graph_calls if self.parent else self._graph_calls

    @property
    def graph_rows(self) -> int:
        return self.parent.graph_rows if self.parent else self._graph_rows

    def cancel(self) -> None:
        self._cancelled.set()

    def absorb(self, other: "PathBudget") -> None:
        """共享冷计算的使用量计入参与请求；不能在装配阶段重新获得一套额度。"""
        self.check()
        if self.parent is not None:
            self.parent.absorb(other)
            return
        if (
            self.graph_calls + other.graph_calls > 256
            or self.graph_rows + other.graph_rows > 20_000
        ):
            raise PathBudgetExceeded("graph_limit")
        self._graph_calls += other.graph_calls
        self._graph_rows += other.graph_rows
        self.sql_steps += other.sql_steps
        if self.sql_steps >= self.sql_limit:
            raise PathBudgetExceeded("sql_limit")

    def check(self) -> None:
        if self._cancelled.is_set():
            raise PathBudgetExceeded("cancelled")
        if self.parent is not None:
            self.parent.check()
        if self.clock() >= self.deadline:
            raise PathBudgetExceeded("time_limit")

    def check_pair(self) -> None:
        self.check()
        if self.pairs >= self.pair_limit:
            raise PathBudgetExceeded("pair_limit")
        self.pairs += 1

    def progress(self) -> int:
        self.sql_steps += 1000
        try:
            if self.parent is not None and self.parent.progress():
                self.interrupted = self.parent.interrupted
                return 1
            self.check()
            if self.sql_steps >= self.sql_limit:
                raise PathBudgetExceeded("sql_limit")
        except PathBudgetExceeded as exc:
            self.interrupted = exc.reason
            return 1
        return 0

    def elapsed_ms(self) -> float:
        return round((self.clock() - self.started) * 1000, 2)
