"""单API进程的异步准入；工作线程结束后才能归还执行名额。"""

import asyncio
import logging
import os
from collections import deque
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from contextvars import copy_context
from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any, Literal, TypeVar
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from relationship_query.domain.path_budget import (
    PathBudget,
    PathBudgetExceeded,
    current_query_budget,
    using_budget,
)
from relationship_query.runtime.diagnostics import (
    DiagnosticTrace,
    capture,
    error_reason,
    link_job,
    observe,
    record_stage,
    request_id,
    terminate,
)
from relationship_query.runtime.fact_indexes import fact_indexes
from relationship_query.runtime.relation_cache import RelationCache
from relationship_query.services.query import QueryError
from relationship_query.services.query_plan import (
    PLAN_CACHE_FORMAT,
    PersonPagePlan,
    cached_plan,
    store_plan,
)

Cost = Literal["heavy", "assembly", "light", "guard", "control"]
T = TypeVar("T")
logger = logging.getLogger("relationship_query.admission")


def busy(reason: str) -> QueryError:
    return QueryError("GRAPH_BUSY", "查询任务已满，请稍后重试", 503, reason=reason)


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
    assembly: int = 2
    compute: int = 2
    assembly_queue: int = 8

    def __post_init__(self) -> None:
        if not (
            2 <= self.workers <= 16
            and 1 <= self.heavy <= self.compute
            and 1 <= self.assembly <= self.compute
            and 1 <= self.compute <= max(1, self.workers - 2)
            and 1 <= self.light < self.workers
            and 0 <= self.heavy_queue <= 16
            and 0 <= self.light_queue <= 16
            and 0 <= self.assembly_queue <= 16
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
    shared: bool = False
    created_at: float = field(default_factory=perf_counter)
    cancelled_at: float | None = None


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
        self._queues: dict[Cost, deque[object]] = {
            "heavy": deque(),
            "assembly": deque(),
            "light": deque(),
            "guard": deque(),
            "control": deque(),
        }
        self._active: dict[Cost, int] = dict.fromkeys(self._queues, 0)
        self._jobs: dict[str, _Job] = {}
        self._flights: dict[str, _Flight] = {}
        self._followers = self._inflight = 0
        self._control_inflight = 0
        self._closed = False
        logger.info(
            "query admission configured limits=%s effective_light=%s",
            asdict(self.limits),
            max(1, self.limits.light - 1),
        )

    @asynccontextmanager
    async def request(self, *, protected: bool = False) -> AsyncIterator[None]:
        full = self._control_inflight >= 3 if protected else self._inflight >= self.limits.inflight
        if self._closed or full:
            observe("admission.request_rejected")
            raise busy("entry_closed" if self._closed else "entry_limit")
        if protected:
            self._control_inflight += 1
        else:
            self._inflight += 1
        try:
            yield
        finally:
            if protected:
                self._control_inflight -= 1
            else:
                self._inflight -= 1

    def snapshot(self) -> dict[str, int]:
        return {
            "inflight": self._inflight,
            "control_inflight": self._control_inflight,
            "followers": self._followers,
            "heavy_active": self._active["heavy"],
            "assembly_active": self._active["assembly"],
            "light_active": self._active["light"],
            "guard_active": self._active["guard"],
            "control_active": self._active["control"],
            "heavy_waiting": len(self._queues["heavy"]),
            "assembly_waiting": len(self._queues["assembly"]),
            "light_waiting": len(self._queues["light"]),
            "guard_waiting": len(self._queues["guard"]),
            "control_waiting": len(self._queues["control"]),
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

    async def page_plan(
        self, key: str, operation: Callable[[], PersonPagePlan], cache: RelationCache | None = None
    ) -> PersonPagePlan:
        """只合并ID计划，完成即移除；存储复用仍由已有RelationCache负责。"""
        if self._closed:
            raise busy("entry_closed")
        caller = current_query_budget() or PathBudget(5000, 5000)
        caller.check()
        arguments = [PLAN_CACHE_FORMAT, key]
        ready = cached_plan(cache, key, caller)
        if ready is not None:
            observe("admission.plan_cached")
            return ready
        flight_key = cache.key(arguments) if cache is not None else key
        flight = self._flights.get(flight_key)
        follower = flight is not None
        if flight is None:
            budget = PathBudget(5000, 5000, inherit_request=False)

            def compute() -> PersonPagePlan:
                result = cached_plan(cache, key, budget) or operation()
                store_plan(cache, result, budget)
                return result

            flight = self._flights[flight_key] = _Flight(
                self._start("heavy", compute, budget, shared=True)
            )
        elif (
            flight.waiters == 0
            or flight.followers >= self.limits.followers_per_key
            or self._followers >= self.limits.followers
        ):
            observe("admission.follower_rejected")
            raise busy("follower_limit")
        if follower:
            self._followers += 1
            flight.followers += 1
        flight.waiters += 1
        observe("admission.plan_follower" if follower else "admission.plan_owner")
        try:
            result = await self._wait(flight.job, caller, "follower" if follower else "owner")
            if not isinstance(result, PersonPagePlan):
                raise TypeError("共享计算必须返回人物ID计划")
            caller.absorb(flight.job.budget)
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
                    self._flights.pop(flight_key, None)

    def _start(
        self, cost: Cost, operation: Callable[[], T], budget: PathBudget, *, shared: bool = False
    ) -> _Job:
        maximum = self.limits.inflight + (3 if cost == "control" else 0)
        if self._closed or len(self._jobs) >= maximum:
            observe("admission.job_rejected")
            raise busy("entry_closed" if self._closed else "job_cap")
        budget.check()
        job = _Job(budget, cost, shared=shared)
        self._jobs[job.identity] = job
        job.task = asyncio.create_task(self._work(job, operation))
        job.task.add_done_callback(lambda task: self._finished(job, task))
        return job

    async def _wait(self, job: _Job, budget: PathBudget, role: str = "execution") -> Any:
        assert job.task is not None
        link_job(job.identity, job.cost, role)
        budget.check()
        timeout = asyncio.timeout(max(0, budget.deadline - budget.clock()))
        started = perf_counter()
        try:
            async with timeout:
                result = await asyncio.shield(job.task)
        except TimeoutError:
            if timeout.expired():
                raise PathBudgetExceeded("time_limit") from None
            raise
        finally:
            record_stage(
                "Plan.shared_wait" if job.shared else "Execution.wait",
                (perf_counter() - started) * 1000,
            )
        budget.check()
        return result

    @staticmethod
    def _cancel(job: _Job) -> None:
        if job.cancelled_at is None:
            job.cancelled_at = perf_counter()
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
        trace = DiagnosticTrace(request_id=request_id(), job_id=job.identity)
        # 共享作业只在job日志计执行量；所有HTTP参与者通过job_id关联等待。
        with (
            capture(trace, include_in_parent=not job.shared),
            fact_indexes(),
            using_budget(job.budget),
        ):
            record_stage("Execution.loop_dispatch_delay", (perf_counter() - job.created_at) * 1000)
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
                terminate(
                    error.reason or error_reason(error.code)
                    if isinstance(error, QueryError)
                    else f"budget.{error.reason}"
                )
                observe(f"error.{error.code if isinstance(error, QueryError) else error.reason}")
                raise
            except asyncio.CancelledError:
                terminate("cancelled")
                raise
            except SQLAlchemyError:
                terminate("dependency")
                observe("execution.failed")
                raise
            except BaseException:
                terminate("internal_error")
                observe("execution.failed")
                raise
            finally:
                if job.cancelled_at is not None:
                    record_stage(
                        "Execution.cancel_response", (perf_counter() - job.cancelled_at) * 1000
                    )
                if acquired:
                    async with self._condition:
                        self._active[job.cost] -= 1
                        self._condition.notify_all()
                logger.info(
                    "query calculation completed request_id=%s job_id=%s cost=%s "
                    "stages=%s observations=%s terminal_reason=%s",
                    trace.request_id,
                    job.identity,
                    job.cost,
                    trace.totals(),
                    trace.observations,
                    trace.terminal_reason or "success",
                )

    async def _acquire(self, job: _Job) -> None:
        ticket = object()
        queue = self._queues[job.cost]
        maximum = {
            "heavy": self.limits.heavy_queue,
            "assembly": self.limits.assembly_queue,
            "light": self.limits.light_queue,
            "guard": self.limits.inflight,
            "control": 2,
        }[job.cost]
        started = perf_counter()
        async with self._condition:
            if not queue and self._available(job.cost):
                self._active[job.cost] += 1
                return
            if len(queue) >= maximum:
                observe(f"admission.{job.cost}_queue_rejected")
                raise busy(f"queue_full.{job.cost}")
            queue.append(ticket)
            try:
                remaining = max(0, job.budget.deadline - job.budget.clock())
                # 已选定计划的装配和短版本检查只受原请求截止限制；不能在每阶段
                # 重开300ms短等待，导致读取完成后又在末尾校验丢弃响应。
                deadline = (
                    remaining
                    if job.cost in ("assembly", "guard")
                    else min(self.limits.queue_seconds, remaining)
                )
                async with asyncio.timeout(deadline):
                    while queue[0] is not ticket or not self._available(job.cost):
                        await self._condition.wait()
                    job.budget.check()
                    self._active[job.cost] += 1
            except TimeoutError:
                job.budget.check()
                observe(f"admission.{job.cost}_queue_timeout")
                raise busy(f"queue_timeout.{job.cost}") from None
            finally:
                queue.remove(ticket)
                record_stage("Execution.queue_wait", (perf_counter() - started) * 1000)
                record_stage(f"Execution.{job.cost}_queue", (perf_counter() - started) * 1000)
                self._condition.notify_all()

    def _available(self, cost: Cost) -> bool:
        if cost in ("control", "guard"):
            # 短文件签名检查复用保留线程；有健康任务排队时先让其执行。
            return (
                self._active["control"] + self._active["guard"] == 0
                and (cost == "control" or not self._queues["control"])
                and sum(self._active.values()) < self.limits.workers
            )
        compute = self._active["heavy"] + self._active["assembly"]
        regular = compute + self._active["light"]
        limit = {
            "heavy": self.limits.heavy,
            "assembly": self.limits.assembly,
            "light": max(1, self.limits.light - 1),
        }[cost]
        # 计算总额独立于线程数；另保留普通候选与短检查的执行机会。
        return (
            self._active[cost] < limit
            and regular < self.limits.workers - 1
            and (cost == "light" or compute < self.limits.compute)
        )

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
