"""ASGI入口统一截止、准入和断开监听；校验来源后才发送响应。"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import AsyncExitStack
from time import perf_counter
from uuid import uuid4

from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from relationship_query.domain.path_budget import (
    PathBudget,
    PathBudgetExceeded,
    shared_relation_budget,
)
from relationship_query.runtime.admission import Cost, QueryAdmission
from relationship_query.runtime.diagnostics import DiagnosticTrace, capture, observe, stage
from relationship_query.services.query import QueryError

logger = logging.getLogger("relationship_query")
ErrorResponse = Callable[[Request, str, str, int], Response]


class QueryHTTPMiddleware:
    def __init__(self, app: ASGIApp, error_response: ErrorResponse) -> None:
        self.app, self.error_response = app, error_response

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        trace = DiagnosticTrace(request_id=uuid4().hex)
        started = perf_counter()
        status = 500
        async with AsyncExitStack() as lifetime:
            with capture(trace, include_in_parent=True), shared_relation_budget() as budget:
                try:
                    admission: QueryAdmission = request.app.state.admission
                    protected = request.url.path in {"/api/v1/health", "/api/v1/meta"}
                    await lifetime.enter_async_context(admission.request(protected=protected))
                    timeout = asyncio.timeout(max(0, budget.deadline - budget.clock()))
                    async with timeout:
                        messages = await self._serve(request, receive, budget)
                except PathBudgetExceeded as error:
                    observe(f"error.{error.reason}")
                    messages = await self._error(
                        request, "GRAPH_QUERY_LIMIT", f"请求达到预算（{error.label}）", 503
                    )
                except TimeoutError:
                    if not timeout.expired():
                        logger.exception("unexpected timeout request_id=%s", trace.request_id)
                        messages = await self._error(
                            request, "INTERNAL_ERROR", "查询服务发生异常", 500
                        )
                    else:
                        budget.cancel()
                        observe("error.time_limit")
                        messages = await self._error(
                            request, "GRAPH_QUERY_LIMIT", "请求达到执行时间预算，请稍后重试", 503
                        )
                except QueryError as error:
                    observe(f"error.{error.code}")
                    messages = await self._error(request, error.code, error.message, error.status)
                except SQLAlchemyError:
                    logger.exception("query storage failure request_id=%s", trace.request_id)
                    messages = await self._error(
                        request, "STORAGE_UNAVAILABLE", "查询存储暂不可用", 503
                    )
                except asyncio.CancelledError:
                    budget.cancel()
                    raise
                except Exception:
                    logger.exception("unexpected query failure request_id=%s", trace.request_id)
                    messages = await self._error(
                        request, "INTERNAL_ERROR", "查询服务发生异常，请稍后重试", 500
                    )
                try:
                    if not messages:
                        status = 499
                        return
                    status = messages[0]["status"]
                    headers = list(messages[0].get("headers", []))
                    headers += [
                        (b"x-request-id", trace.request_id.encode()),
                        (
                            b"server-timing",
                            f"app;dur={(perf_counter() - started) * 1000:.1f}".encode(),
                        ),
                    ]
                    messages[0]["headers"] = headers
                    for message in messages:
                        await send(message)
                finally:
                    logger.info(
                        "query request completed request_id=%s method=%s route=%s status=%s "
                        "elapsed_ms=%.2f stages=%s observations=%s jobs=%s",
                        trace.request_id,
                        request.method,
                        getattr(scope.get("route"), "path", "unmatched"),
                        status,
                        (perf_counter() - started) * 1000,
                        trace.totals(),
                        trace.observations,
                        trace.jobs,
                    )

    async def _serve(self, request: Request, receive: Receive, budget: PathBudget) -> list[Message]:
        protected = request.url.path in {"/api/v1/health", "/api/v1/meta"}
        body = await self._body(receive)
        if body is None:
            budget.cancel()
            observe("http.disconnected")
            return []
        disconnected = asyncio.Event()
        received = False

        async def replay() -> Message:
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        task = asyncio.create_task(
            self._dispatch(request, replay, "control" if protected else "light")
        )

        async def watch() -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    disconnected.set()
                    budget.cancel()
                    observe("http.disconnected")
                    task.cancel()
                    return

        watcher = asyncio.create_task(watch())
        try:
            return await task
        except asyncio.CancelledError:
            if disconnected.is_set():
                return []
            raise
        finally:
            watcher.cancel()
            if not task.done():
                task.cancel()
            await asyncio.gather(watcher, task, return_exceptions=True)

    async def _dispatch(self, request: Request, receive: Receive, cost: Cost) -> list[Message]:
        admission: QueryAdmission = request.app.state.admission
        guard = getattr(request.app.state, "source_guard", None)
        messages: list[Message] = []
        if guard:
            with stage("SourceGuard.before"):
                await admission.execute(cost, guard.verify_snapshot)
        await self.app(request.scope, receive, self._collector(messages))
        if guard:
            with stage("SourceGuard.after"):
                await admission.execute(cost, guard.verify_snapshot)
        return messages

    @staticmethod
    def _collector(messages: list[Message]) -> Send:
        async def collect(message: Message) -> None:
            messages.append(message)

        return collect

    @staticmethod
    async def _body(receive: Receive) -> bytes | None:
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return None
            part = message.get("body", b"")
            size += len(part)
            if size > 1024 * 1024:
                raise QueryError("BODY_TOO_LARGE", "请求内容超过1MiB上限", 413)
            chunks.append(part)
            if not message.get("more_body", False):
                return b"".join(chunks)

    async def _error(self, request: Request, code: str, message: str, status: int) -> list[Message]:
        messages: list[Message] = []
        await self.error_response(request, code, message, status)(
            request.scope, request.receive, self._collector(messages)
        )
        return messages
