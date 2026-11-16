"""启动／关闭的阻塞资源操作离开事件循环，取消也须等待实际清理结束。"""

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, asynccontextmanager
from functools import partial
from typing import TypeVar

T = TypeVar("T")


async def _join(task: asyncio.Task[T]) -> tuple[T, bool]:
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
    return task.result(), interrupted


async def offload(operation: Callable[[], T]) -> T:
    result, interrupted = await _join(asyncio.create_task(asyncio.to_thread(operation)))
    if interrupted:
        raise asyncio.CancelledError
    return result


@asynccontextmanager
async def offloaded(manager: AbstractContextManager[T]) -> AsyncIterator[T]:
    value, interrupted = await _join(asyncio.create_task(asyncio.to_thread(manager.__enter__)))
    if interrupted:
        await offload(
            partial(manager.__exit__, asyncio.CancelledError, asyncio.CancelledError(), None)
        )
        raise asyncio.CancelledError
    try:
        yield value
    except BaseException:
        suppressed = await offload(partial(manager.__exit__, *sys.exc_info()))
        if not suppressed:
            raise
    else:
        await offload(partial(manager.__exit__, None, None, None))
