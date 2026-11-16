"""单API进程的异步准入；工作线程结束后才能归还执行名额。"""

import asyncio
import logging
import os
from collections import deque
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from contextvars import copy_context
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal, TypeVar
from uuid import uuid4

from relationship_query.domain.path_budget import (
    PathBudget,
    PathBudgetExceeded,
    current_query_budget,
    using_budget,
)
from relationship_query.runtime.diagnostics import (
    DiagnosticTrace,
    capture,
    observe,
    record_stage,
    request_id,
)
from relationship_query.services.query import QueryError
from relationship_query.services.query_plan import PersonPagePlan

Cost = Literal["heavy", "light"]
T = TypeVar("T")
logger = logging.getLogger("relationship_query.admission")


def busy() -> QueryError:
    return QueryError("GRAPH_BUSY", "查询任务已满，请稍后重试", 503)


@dataclass(frozen=True)
class AdmissionLimits:
    workers: int = 4
    heavy: int = 1
    light: int = 3
    heavy_queue: int = 2
    light_queue: int = 8
    queue_seconds: float = 0.3
    inflight: int = 16
    followers_per_key: int = 4
    followers: int = 8

    def __post_init__(self) -> None:
        if not (
            2 <= self.workers <= 4
            and 1 <= self.heavy < self.workers
            and 1 <= self.light < self.workers
            and 0 <= self.heavy_queue <= 16
            and 0 <= self.light_queue <= 16
            and 0 < self.queue_seconds <= 1
            and 1 <= self.inflight <= 64
            and 0 <= self.followers_per_key <= self.followers <= 32
        ):
            raise ValueError("查询准入配置超出受支持的单进程资源范围")

    @classmethod
    def configured(cls) -> "AdmissionLimits":
        defaults = cls()
        values = {}
        for name in cls.__dataclass_fields__:
            value = os.environ.get(f"RELATIONSHIP_ADMISSION_{name.upper()}")
            if value is not None:
                values[name] = float(value) if name == "queue_seconds" else int(value)
        return cls(**{**defaults.__dict__, **values})


@dataclass
class _Job:
    budget: PathBudget
    cost: Cost
    identity: str = field(default_factory=lambda: uuid4().hex)
    started: bool = False
    task: asyncio.Task[Any] | None = None


@dataclass
class _Flight:
    job: _Job
    waiters: int = 0
    followers: int = 0


class QueryAdmission:
    def __init__(self, limits: AdmissionLimits | None = None) -> None:
        self.limits = limits or AdmissionLimits.configured()
        self._executor = ThreadPoolExecutor(
            max_workers=self.limits.workers, thread_name_prefix="relationship-query"
        )
        self._condition = asyncio.Condition()
        self._queues: dict[Cost, deque[object]] = {"heavy": deque(), "light": deque()}
        self._active: dict[Cost, int] = {"heavy": 0, "light": 0}
        self._jobs: dict[str, _Job] = {}
        self._flights: dict[str, _Flight] = {}
        self._followers = self._inflight = 0
        self._closed = False

    @asynccontextmanager
    async def request(self) -> AsyncIterator[None]:
        if self._closed or self._inflight >= self.limits.inflight:
            observe("admission.request_rejected")
            raise busy()
        self._inflight += 1
        try:
            yield
        finally:
            self._inflight -= 1

    def snapshot(self) -> dict[str, int]:
        return {
            "inflight": self._inflight,
            "followers": self._followers,
            "heavy_active": self._active["heavy"],
            "light_active": self._active["light"],
            "heavy_waiting": len(self._queues["heavy"]),
            "light_waiting": len(self._queues["light"]),
            "jobs": len(self._jobs),
            "flights": len(self._flights),
        }

    async def execute(self, cost: Cost, operation: Callable[[], T]) -> T:
        budget = current_query_budget() or PathBudget(5000, 5000)
        job = self._start(cost, operation, budget)
        try:
            return await self._wait(job, budget)
        except (asyncio.CancelledError, PathBudgetExceeded):
            self._cancel(job)
            raise

    async def page_plan(self, key: str, operation: Callable[[], PersonPagePlan]) -> PersonPagePlan:
        """只合并ID计划，完成即移除；存储复用仍由已有RelationCache负责。"""
        if self._closed:
            raise busy()
        caller = current_query_budget() or PathBudget(5000, 5000)
        caller.check()
        flight = self._flights.get(key)
        follower = flight is not None
        if flight is None:
            budget = PathBudget(5000, 5000, inherit_request=False)
            flight = self._flights[key] = _Flight(self._start("heavy", operation, budget))
        elif (
            flight.waiters == 0
            or flight.followers >= self.limits.followers_per_key
            or self._followers >= self.limits.followers
        ):
            observe("admission.follower_rejected")
            raise busy()
        if follower:
            self._followers += 1
            flight.followers += 1
        flight.waiters += 1
        observe("admission.plan_follower" if follower else "admission.plan_owner")
        try:
            result = await self._wait(flight.job, caller)
            if not isinstance(result, PersonPagePlan):
                raise TypeError("共享计算必须返回人物ID计划")
            return result
        finally:
            flight.waiters -= 1
            if follower:
                self._followers -= 1
                flight.followers -= 1
            if flight.waiters == 0:
                if flight.job.task is not None and not flight.job.task.done():
                    self._cancel(flight.job)
                else:
                    self._flights.pop(key, None)

    def _start(self, cost: Cost, operation: Callable[[], T], budget: PathBudget) -> _Job:
        if self._closed or len(self._jobs) >= self.limits.inflight:
            raise busy()
        budget.check()
        job = _Job(budget, cost)
        self._jobs[job.identity] = job
        job.task = asyncio.create_task(self._work(job, operation))
        job.task.add_done_callback(lambda task: self._finished(job, task))
        return job

    async def _wait(self, job: _Job, budget: PathBudget) -> Any:
        assert job.task is not None
        budget.check()
        timeout = asyncio.timeout(max(0, budget.deadline - budget.clock()))
        try:
            async with timeout:
                result = await asyncio.shield(job.task)
        except TimeoutError:
            if timeout.expired():
                raise PathBudgetExceeded("time_limit") from None
            raise
        budget.check()
        return result

    @staticmethod
    def _cancel(job: _Job) -> None:
        job.budget.cancel()
        if not job.started and job.task is not None:
            job.task.cancel()

    def _finished(self, job: _Job, task: asyncio.Task[Any]) -> None:
        self._jobs.pop(job.identity, None)
        for key, flight in list(self._flights.items()):
            if flight.job is job and flight.waiters == 0:
                self._flights.pop(key, None)
        # 调用者已离开时也消费异常；活跃调用者仍通过await取得同一异常。
        if not task.cancelled():
            task.exception()

    async def _work(self, job: _Job, operation: Callable[[], T]) -> T:
        trace = DiagnosticTrace(request_id=request_id())
        with capture(trace, include_in_parent=True), using_budget(job.budget):
            acquired = False
            try:
                await self._acquire(job)
                acquired = True
                job.started = True
                context = copy_context()
                submitted = perf_counter()

                def run() -> T:
                    record_stage("Execution.thread_start", (perf_counter() - submitted) * 1000)
                    job.budget.check()
                    result = operation()
                    job.budget.check()
                    return result

                return await asyncio.get_running_loop().run_in_executor(
                    self._executor, context.run, run
                )
            except (QueryError, PathBudgetExceeded) as error:
                observe(f"error.{error.code if isinstance(error, QueryError) else error.reason}")
                raise
            except BaseException:
                observe("execution.failed")
                raise
            finally:
                if acquired:
                    async with self._condition:
                        self._active[job.cost] -= 1
                        self._condition.notify_all()
                logger.info(
                    "query calculation completed request_id=%s job_id=%s cost=%s "
                    "stages=%s observations=%s",
                    trace.request_id,
                    job.identity,
                    job.cost,
                    trace.totals(),
                    trace.observations,
                )

    async def _acquire(self, job: _Job) -> None:
        ticket = object()
        queue = self._queues[job.cost]
        maximum = self.limits.heavy_queue if job.cost == "heavy" else self.limits.light_queue
        started = perf_counter()
        async with self._condition:
            if not queue and self._available(job.cost):
                self._active[job.cost] += 1
                return
            if len(queue) >= maximum:
                observe(f"admission.{job.cost}_queue_rejected")
                raise busy()
            queue.append(ticket)
            try:
                deadline = min(
                    self.limits.queue_seconds, max(0, job.budget.deadline - job.budget.clock())
                )
                async with asyncio.timeout(deadline):
                    while queue[0] is not ticket or not self._available(job.cost):
                        await self._condition.wait()
                    job.budget.check()
                    self._active[job.cost] += 1
            except TimeoutError:
                job.budget.check()
                observe(f"admission.{job.cost}_queue_timeout")
                raise busy() from None
            finally:
                queue.remove(ticket)
                record_stage("Execution.queue_wait", (perf_counter() - started) * 1000)
                self._condition.notify_all()

    def _available(self, cost: Cost) -> bool:
        limit = self.limits.heavy if cost == "heavy" else self.limits.light
        return self._active[cost] < limit and sum(self._active.values()) < self.limits.workers

    async def close(self) -> None:
        self._closed = True
        jobs = list(self._jobs.values())
        for job in jobs:
            self._cancel(job)
        drain = asyncio.gather(*(job.task for job in jobs if job.task), return_exceptions=True)
        cancelled = False
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                # 关闭协程被取消也不能提前关闭仍被线程使用的SQL／图资源。
                cancelled = True
        self._executor.shutdown(wait=True, cancel_futures=True)
        if cancelled:
            raise asyncio.CancelledError
