import asyncio
from contextlib import contextmanager
from threading import Event

import pytest

from relationship_query.runtime.lifecycle import offload, offloaded


def test_startup_cancel_waits_for_enter_then_closes_resource():
    async def scenario():
        loop = asyncio.get_running_loop()
        entered, release = asyncio.Event(), Event()
        closed = []

        @contextmanager
        def resource():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(2)
            try:
                yield "ready"
            finally:
                closed.append(True)

        async def start():
            async with offloaded(resource()):
                pytest.fail("取消后不应进入服务")

        task = asyncio.create_task(start())
        try:
            await entered.wait()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not closed
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert closed == [True]

    asyncio.run(scenario())


def test_offloaded_context_preserves_exception_and_exit_semantics():
    async def scenario():
        closed = []

        @contextmanager
        def resource():
            try:
                yield 3
            except ValueError:
                closed.append("suppressed")
            finally:
                closed.append("closed")

        async with offloaded(resource()) as value:
            assert value == 3
            raise ValueError("test")
        assert closed == ["suppressed", "closed"]

        def failure():
            raise RuntimeError("preserved")

        with pytest.raises(RuntimeError, match="preserved"):
            await offload(failure)

    asyncio.run(scenario())
