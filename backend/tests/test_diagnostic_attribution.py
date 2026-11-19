"""拒绝来源与共享作业执行量属于原始上下文，不能按等待人数放大。"""

import asyncio
import logging

import pytest
from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from relationship_query.runtime.admission import AdmissionLimits, QueryAdmission
from relationship_query.runtime.diagnostics import DiagnosticTrace, capture, observe, terminate
from relationship_query.runtime.http import QueryHTTPMiddleware
from relationship_query.services.query import QueryError
from tests.test_query_admission import Blocked, state


def test_terminal_reason_is_not_overwritten_by_error_formatting():
    trace = DiagnosticTrace()
    with capture(trace):
        terminate("queue_full.heavy")
        terminate("application_error")
    assert trace.terminal_reason == "queue_full.heavy"


def test_shared_execution_logged_once_and_waiters_only_link_job(caplog):
    async def scenario():
        admission = QueryAdmission()
        blocked = Blocked()
        owner_trace, follower_trace = DiagnosticTrace(), DiagnosticTrace()

        def operation():
            observe("graph.rpc", 7)
            return blocked()

        try:
            with capture(owner_trace):
                owner = asyncio.create_task(admission.page_plan("same", operation))
            await blocked.entered.wait()
            with capture(follower_trace):
                follower = asyncio.create_task(admission.page_plan("same", operation))
            await state(admission, "followers", 1)
            blocked.release.set()
            await asyncio.gather(owner, follower)
            assert owner_trace.jobs[0][0] == follower_trace.jobs[0][0]
            for trace in (owner_trace, follower_trace):
                assert "graph.rpc" not in trace.observations
                assert "Plan.shared_wait" in trace.totals()
            await state(admission, "jobs", 0)
        finally:
            blocked.release.set()
            await admission.close()

    with caplog.at_level(logging.INFO, logger="relationship_query.admission"):
        asyncio.run(scenario())
    records = [r.getMessage() for r in caplog.records if "calculation completed" in r.message]
    assert len(records) == 1
    assert "'graph.rpc': 7" in records[0] and "terminal_reason=success" in records[0]


def test_entry_and_queue_rejections_keep_distinct_causes():
    async def scenario():
        admission = QueryAdmission(AdmissionLimits(inflight=1, heavy_queue=0))
        blocked = Blocked()
        try:
            async with admission.request():
                with pytest.raises(QueryError) as rejected:
                    async with admission.request():
                        pytest.fail("入口超额")
                assert rejected.value.reason == "entry_limit"
            running = asyncio.create_task(admission.execute("heavy", blocked))
            await blocked.entered.wait()
            # job-cap使用独立额度，先提高上限以实际抵达重队列拒绝点。
            admission.limits = AdmissionLimits(inflight=2, heavy_queue=0)
            with pytest.raises(QueryError) as rejected:
                await admission.execute("heavy", blocked)
            assert rejected.value.reason == "queue_full.heavy"
            blocked.release.set()
            await running
        finally:
            blocked.release.set()
            await admission.close()

    asyncio.run(scenario())


def test_sql_job_failure_preserves_dependency_classification(caplog):
    async def scenario():
        admission = QueryAdmission()

        def failed():
            raise SQLAlchemyError("private error text")

        try:
            with pytest.raises(SQLAlchemyError):
                await admission.execute("light", failed)
        finally:
            await admission.close()

    with caplog.at_level(logging.INFO, logger="relationship_query.admission"):
        asyncio.run(scenario())
    assert "terminal_reason=dependency" in caplog.text
    assert "private error text" not in caplog.text


def test_response_send_failure_is_not_logged_as_success(caplog, monkeypatch):
    async def serve(*args):
        return [
            {"type": "http.response.start", "status": 200, "headers": []},
            {"type": "http.response.body", "body": b"ok"},
        ]

    async def send(message):
        raise ConnectionError("transport closed")

    async def receive():
        pytest.fail("mocked serve must not receive")

    async def scenario():
        app = FastAPI()
        app.state.admission = QueryAdmission()
        middleware = QueryHTTPMiddleware(app, lambda *args: Response())
        scope = {
            "type": "http",
            "app": app,
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/meta",
            "query_string": b"",
            "headers": [],
        }
        try:
            with pytest.raises(ConnectionError):
                await middleware(scope, receive, send)
            assert app.state.admission.snapshot()["control_inflight"] == 0
        finally:
            await app.state.admission.close()

    monkeypatch.setattr(QueryHTTPMiddleware, "_serve", serve)
    with caplog.at_level(logging.INFO, logger="relationship_query"):
        asyncio.run(scenario())
    records = [r.getMessage() for r in caplog.records if "query request completed" in r.message]
    assert len(records) == 1 and "terminal_reason=send_failure" in records[0]
