"""真实线程阻塞验证异步等待与执行租约，不用HTTP返回完成代替后台结束。"""

import asyncio
from threading import Event

import pytest

from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded, using_budget
from relationship_query.runtime.admission import AdmissionLimits, QueryAdmission
from relationship_query.services.query import QueryError
from relationship_query.services.query_plan import PersonPagePlan


def plan():
    return PersonPagePlan("v1", 202611, "p:1", "scope", ("p:2",), False, None)


class Blocked:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.release = Event()
        self.calls = 0

    def __call__(self):
        self.calls += 1
        self.loop.call_soon_threadsafe(self.entered.set)
        assert self.release.wait(2), "测试未解除工作线程阻塞"
        return plan()


async def state(admission, name, value):
    async with asyncio.timeout(1):
        while admission.snapshot()[name] != value:
            await asyncio.sleep(0)


def test_heavy_queue_bounded_and_light_execution_remains_available():
    async def scenario():
        admission = QueryAdmission()
        heavy, lights = Blocked(), [Blocked() for _ in range(3)]
        try:
            running = asyncio.create_task(admission.execute("heavy", heavy))
            await heavy.entered.wait()
            queued = [asyncio.create_task(admission.execute("heavy", plan)) for _ in range(2)]
            await state(admission, "heavy_waiting", 2)
            with pytest.raises(QueryError) as rejected:
                await admission.execute("heavy", plan)
            assert rejected.value.code == "GRAPH_BUSY"
            tasks = [asyncio.create_task(admission.execute("light", light)) for light in lights]
            await asyncio.gather(*(light.entered.wait() for light in lights))
            assert admission.snapshot()["light_active"] == 3
            assert admission.snapshot()["heavy_active"] == 1
            for light in lights:
                light.release.set()
            assert await asyncio.gather(*tasks) == [plan()] * 3
            heavy.release.set()
            assert await asyncio.gather(running, *queued) == [plan()] * 3
            await state(admission, "jobs", 0)
        finally:
            heavy.release.set()
            for light in lights:
                light.release.set()
            await admission.close()

    asyncio.run(scenario())


def test_queue_wait_limit_is_busy_without_starting_another_worker():
    async def scenario():
        admission = QueryAdmission(AdmissionLimits(queue_seconds=0.02))
        blocked = Blocked()
        try:
            task = asyncio.create_task(admission.execute("heavy", blocked))
            await blocked.entered.wait()
            with pytest.raises(QueryError) as rejected:
                await admission.execute("heavy", plan)
            assert rejected.value.code == "GRAPH_BUSY"
            assert admission.snapshot()["heavy_waiting"] == 0
            assert admission.snapshot()["heavy_active"] == 1
            blocked.release.set()
            await task
        finally:
            blocked.release.set()
            await admission.close()

    asyncio.run(scenario())


def test_request_inflight_limit_and_error_release():
    async def scenario():
        admission = QueryAdmission(AdmissionLimits(inflight=2))
        try:
            async with admission.request(), admission.request():
                with pytest.raises(QueryError):
                    async with admission.request():
                        pytest.fail("超额请求进入")
            assert admission.snapshot()["inflight"] == 0

            def failure():
                raise ValueError("preserved")

            with pytest.raises(ValueError, match="preserved"):
                await admission.execute("light", failure)
            assert await admission.execute("light", lambda: 7) == 7
        finally:
            await admission.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_caller_exit_does_not_release_a_running_worker_lease(cancel):
    async def scenario():
        admission = QueryAdmission(AdmissionLimits(queue_seconds=0.01))
        blocked = Blocked()
        try:
            with using_budget(PathBudget(5000 if cancel else 20, 100)):
                task = asyncio.create_task(admission.execute("heavy", blocked))
            await blocked.entered.wait()
            if cancel:
                task.cancel()
            with pytest.raises(asyncio.CancelledError if cancel else PathBudgetExceeded):
                await task
            assert admission.snapshot()["heavy_active"] == 1
            with pytest.raises(QueryError):
                await admission.execute("heavy", plan)
            blocked.release.set()
            await state(admission, "jobs", 0)
            assert admission.snapshot()["heavy_active"] == 0
        finally:
            blocked.release.set()
            await admission.close()

    asyncio.run(scenario())


def test_same_key_has_one_worker_and_bounded_followers():
    async def scenario():
        admission = QueryAdmission(AdmissionLimits(followers_per_key=2))
        blocked = Blocked()
        try:
            owner = asyncio.create_task(admission.page_plan("same", blocked))
            await blocked.entered.wait()
            followers = [
                asyncio.create_task(admission.page_plan("same", blocked)) for _ in range(2)
            ]
            await state(admission, "followers", 2)
            with pytest.raises(QueryError):
                await admission.page_plan("same", blocked)
            assert admission.snapshot()["heavy_active"] == 1 and blocked.calls == 1
            blocked.release.set()
            assert await asyncio.gather(owner, *followers) == [plan()] * 3
            assert admission.snapshot()["followers"] == 0
        finally:
            blocked.release.set()
            await admission.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("owner_leaves", [False, True])
def test_one_waiter_leaving_does_not_cancel_shared_calculation(owner_leaves):
    async def scenario():
        admission = QueryAdmission()
        blocked = Blocked()
        try:
            owner = asyncio.create_task(admission.page_plan("same", blocked))
            await blocked.entered.wait()
            with using_budget(PathBudget(5000 if owner_leaves else 20, 100)):
                follower = asyncio.create_task(admission.page_plan("same", blocked))
            await state(admission, "followers", 1)
            if owner_leaves:
                owner.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await owner
            else:
                with pytest.raises(PathBudgetExceeded):
                    await follower
            blocked.release.set()
            assert await (follower if owner_leaves else owner) == plan()
            assert blocked.calls == 1
        finally:
            blocked.release.set()
            await admission.close()

    asyncio.run(scenario())


def test_all_waiters_leaving_removes_queued_plan_without_executing_it():
    async def scenario():
        admission = QueryAdmission()
        blocked, never_run = Blocked(), Blocked()
        try:
            running = asyncio.create_task(admission.execute("heavy", blocked))
            await blocked.entered.wait()
            waiting = asyncio.create_task(admission.page_plan("queued", never_run))
            await state(admission, "heavy_waiting", 1)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            await state(admission, "heavy_waiting", 0)
            assert never_run.calls == 0
            blocked.release.set()
            await running
            await state(admission, "jobs", 0)
            assert admission.snapshot()["flights"] == 0
        finally:
            blocked.release.set()
            never_run.release.set()
            await admission.close()

    asyncio.run(scenario())


def test_shared_failure_reaches_all_waiters_and_next_attempt_can_retry():
    async def scenario():
        admission = QueryAdmission()
        blocked = Blocked()

        def failure():
            blocked()
            raise RuntimeError("shared failure")

        try:
            owner = asyncio.create_task(admission.page_plan("same", failure))
            await blocked.entered.wait()
            follower = asyncio.create_task(admission.page_plan("same", failure))
            await state(admission, "followers", 1)
            blocked.release.set()
            results = await asyncio.gather(owner, follower, return_exceptions=True)
            assert all(isinstance(result, RuntimeError) for result in results)
            assert blocked.calls == 1
            assert await admission.page_plan("same", plan) == plan()
        finally:
            blocked.release.set()
            await admission.close()

    asyncio.run(scenario())


def test_closing_waits_for_actual_worker_then_rejects_new_work():
    async def scenario():
        admission = QueryAdmission()
        blocked = Blocked()
        task = asyncio.create_task(admission.execute("heavy", blocked))
        await blocked.entered.wait()
        closing = asyncio.create_task(admission.close())
        await asyncio.sleep(0)
        try:
            assert not closing.done() and admission.snapshot()["heavy_active"] == 1
            with pytest.raises(QueryError):
                await admission.execute("light", plan)
        finally:
            blocked.release.set()
            await closing
        with pytest.raises(PathBudgetExceeded):
            await task
        assert all(value == 0 for value in admission.snapshot().values())

    asyncio.run(scenario())


def test_operation_timeout_error_is_not_mislabelled_as_request_deadline():
    async def scenario():
        admission = QueryAdmission()
        try:

            def failure():
                raise TimeoutError("dependency-specific")

            with pytest.raises(TimeoutError, match="dependency-specific"):
                await admission.execute("light", failure)
        finally:
            await admission.close()

    asyncio.run(scenario())


def test_global_follower_limit_applies_across_different_keys():
    async def scenario():
        admission = QueryAdmission(AdmissionLimits(followers=1, followers_per_key=1))
        blocked = Blocked()
        try:
            owner = asyncio.create_task(admission.page_plan("a", blocked))
            await blocked.entered.wait()
            follower = asyncio.create_task(admission.page_plan("a", blocked))
            await state(admission, "followers", 1)
            other = asyncio.create_task(admission.page_plan("b", plan))
            await state(admission, "heavy_waiting", 1)
            with pytest.raises(QueryError):
                await admission.page_plan("b", plan)
            blocked.release.set()
            assert await asyncio.gather(owner, follower, other) == [plan()] * 3
        finally:
            blocked.release.set()
            await admission.close()

    asyncio.run(scenario())


def test_short_caller_deadline_does_not_restart_when_queued():
    async def scenario():
        admission, blocked = QueryAdmission(), Blocked()
        try:
            running = asyncio.create_task(admission.execute("heavy", blocked))
            await blocked.entered.wait()
            with using_budget(PathBudget(10, 100)):
                with pytest.raises(PathBudgetExceeded):
                    await admission.execute("heavy", plan)
            await state(admission, "heavy_waiting", 0)
            assert admission.snapshot()["heavy_active"] == 1
            blocked.release.set()
            await running
        finally:
            blocked.release.set()
            await admission.close()

    asyncio.run(scenario())


def test_cancelled_shutdown_still_drains_actual_worker():
    async def scenario():
        admission, blocked = QueryAdmission(), Blocked()
        running = asyncio.create_task(admission.execute("heavy", blocked))
        await blocked.entered.wait()
        closing = asyncio.create_task(admission.close())
        await asyncio.sleep(0)
        closing.cancel()
        await asyncio.sleep(0)
        try:
            assert not closing.done()
            assert admission.snapshot()["heavy_active"] == 1
        finally:
            blocked.release.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
        with pytest.raises(PathBudgetExceeded):
            await running
        assert admission.snapshot()["jobs"] == 0
        assert admission.snapshot()["heavy_active"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "overrides",
    [
        {"workers": 1},
        {"heavy": 0},
        {"heavy": 4},
        {"light": 4},
        {"heavy_queue": -1},
        {"queue_seconds": 0},
        {"followers_per_key": 9, "followers": 8},
    ],
)
def test_invalid_resource_configuration_fails_before_start(overrides):
    with pytest.raises(ValueError):
        AdmissionLimits(**overrides)
