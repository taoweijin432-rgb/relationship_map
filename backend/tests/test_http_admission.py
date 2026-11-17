"""实际ASGI请求覆盖准入、健康隔离、断开和持续在途线程。"""

import asyncio
import json
from pathlib import Path
from threading import Event

import httpx
import pytest

from relationship_query.app import create_app
from relationship_query.infrastructure.fixtures import make_dataset
from relationship_query.infrastructure.sqlite import load_dataset, open_engine


def app_for(tmp_path: Path):
    path = tmp_path / "http.sqlite"
    engine = open_engine(path)
    load_dataset(engine, make_dataset())
    engine.dispose()
    return create_app(path)


async def wait_state(admission, field, expected):
    async with asyncio.timeout(2):
        while admission.snapshot()[field] != expected:
            await asyncio.sleep(0.001)


def test_real_routes_reject_full_heavy_queue_and_preserve_health_and_light_reads(tmp_path):
    async def scenario():
        app = app_for(tmp_path)
        async with app.router.lifespan_context(app):
            runtime = app.state.query_dispatch
            entered, release = asyncio.Event(), Event()
            loop = asyncio.get_running_loop()
            original = runtime.query.compare

            def blocked(left, right):
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(2)
                return original(left, right)

            runtime.query.compare = blocked
            runtime.query.repository.counts = lambda: pytest.fail("meta重复读取统计")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:

                async def compare():
                    return await client.post(
                        "/api/v1/persons/compare",
                        json={
                            "reference_id": "p:000001",
                            "candidate_id": "p:000002",
                        },
                    )

                tasks = [asyncio.create_task(compare())]
                try:
                    await entered.wait()
                    tasks += [asyncio.create_task(compare()) for _ in range(2)]
                    await wait_state(runtime.admission, "heavy_waiting", 2)
                    rejected = await compare()
                    assert rejected.status_code == 503 and rejected.json()["code"] == "GRAPH_BUSY"
                    assert rejected.headers["Retry-After"] == "1"
                    detail = await client.post(
                        "/api/v1/persons/p:000002/details",
                        json={"reference_id": "p:000001"},
                    )
                    assert detail.status_code == 503 and detail.json()["code"] == "GRAPH_BUSY"
                    plain_detail = await client.post("/api/v1/persons/p:000002/details", json={})
                    assert plain_detail.status_code == 200, plain_detail.text
                    for path in ("/api/v1/health", "/api/v1/meta", "/api/v1/persons/suggest"):
                        response = await client.get(path)
                        assert response.status_code == 200, response.text
                    assert runtime.admission.snapshot()["heavy_active"] == 1
                finally:
                    release.set()
                    responses = await asyncio.gather(*tasks)
                assert all(response.status_code == 200 for response in responses)
                assert runtime.query.repository.engine.pool.checkedout() == 0

    asyncio.run(scenario())


def test_asgi_disconnect_does_not_return_worker_capacity_early(tmp_path):
    async def scenario():
        app = app_for(tmp_path)
        async with app.router.lifespan_context(app):
            admission = app.state.admission
            entered, release = asyncio.Event(), Event()
            loop = asyncio.get_running_loop()
            original = app.state.query_service.compare

            def blocked(left, right):
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(2)
                return original(left, right)

            app.state.query_service.compare = blocked
            events = asyncio.Queue()
            await events.put(
                {
                    "type": "http.request",
                    "body": json.dumps(
                        {
                            "reference_id": "p:000001",
                            "candidate_id": "p:000002",
                        }
                    ).encode(),
                    "more_body": False,
                }
            )
            sent = []

            async def send(message):
                sent.append(message)

            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/persons/compare",
                "raw_path": b"/api/v1/persons/compare",
                "query_string": b"",
                "root_path": "",
                "server": ("test", 80),
                "client": ("127.0.0.1", 10),
                "headers": [(b"content-type", b"application/json")],
            }
            request = asyncio.create_task(app(scope, events.get, send))
            try:
                await entered.wait()
                await events.put({"type": "http.disconnect"})
                await asyncio.wait_for(request, timeout=0.5)
                assert not sent
                assert admission.snapshot()["heavy_active"] == 1
                assert admission.snapshot()["inflight"] == 0
            finally:
                release.set()
                await request
            await wait_state(admission, "jobs", 0)
            assert admission.snapshot()["heavy_active"] == 0
            assert app.state.query_service.repository.engine.pool.checkedout() == 0

    asyncio.run(scenario())


def test_inflight_limit_does_not_exclude_health(tmp_path, monkeypatch):
    monkeypatch.setenv("RELATIONSHIP_ADMISSION_INFLIGHT", "1")

    async def scenario():
        app = app_for(tmp_path)
        async with app.router.lifespan_context(app):
            entered, release = asyncio.Event(), Event()
            loop = asyncio.get_running_loop()
            original = app.state.query_service.facts

            def blocked(identity):
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(2)
                return original(identity)

            app.state.query_service.facts = blocked
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                task = asyncio.create_task(client.get("/api/v1/persons/p:000001/facts"))
                try:
                    await entered.wait()
                    rejected = await client.get("/api/v1/persons/suggest")
                    assert rejected.status_code == 503 and rejected.json()["code"] == "GRAPH_BUSY"
                    assert (await client.get("/api/v1/health")).status_code == 200
                finally:
                    release.set()
                    assert (await task).status_code == 200

    asyncio.run(scenario())


def test_request_body_is_bounded_before_dispatch(client):
    response = client.post("/api/v1/persons/search", content=b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413 and response.json()["code"] == "BODY_TOO_LARGE"
    assert client.get("/api/v1/health").status_code == 200


def test_slow_response_send_keeps_inflight_lease(tmp_path, monkeypatch):
    monkeypatch.setenv("RELATIONSHIP_ADMISSION_INFLIGHT", "1")

    async def scenario():
        app = app_for(tmp_path)
        async with app.router.lifespan_context(app):
            events = asyncio.Queue()
            await events.put({"type": "http.request", "body": b"", "more_body": False})
            sending, release = asyncio.Event(), asyncio.Event()

            async def send(message):
                if message["type"] == "http.response.body":
                    sending.set()
                    await release.wait()

            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/v1/persons/suggest",
                "raw_path": b"/api/v1/persons/suggest",
                "query_string": b"",
                "root_path": "",
                "server": ("test", 80),
                "client": ("127.0.0.1", 10),
                "headers": [],
            }
            task = asyncio.create_task(app(scope, events.get, send))
            try:
                await sending.wait()
                assert app.state.admission.snapshot()["inflight"] == 1
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client:
                    rejected = await client.get("/api/v1/persons/suggest")
                    assert rejected.status_code == 503 and rejected.json()["code"] == "GRAPH_BUSY"
                    assert (await client.get("/api/v1/health")).status_code == 200
            finally:
                release.set()
                await task
            assert app.state.admission.snapshot()["inflight"] == 0

    asyncio.run(scenario())


def test_source_guard_failure_never_sends_the_buffered_success(client, monkeypatch):
    from relationship_query.services.query import QueryError

    calls = []

    class Guard:
        def verify_snapshot(self):
            calls.append(1)
            if len(calls) == 2:
                raise QueryError("DATA_VERSION_CHANGED", "test-only", 409)

    monkeypatch.setattr(client.app.state, "source_guard", Guard(), raising=False)
    response = client.get("/api/v1/meta")
    assert response.status_code == 409 and response.json()["code"] == "DATA_VERSION_CHANGED"
    assert calls == [1, 1]


def test_long_assembly_does_not_block_real_suggestions_or_final_source_guard(tmp_path):
    async def scenario():
        app = app_for(tmp_path)
        async with app.router.lifespan_context(app):
            admission = app.state.admission
            loop = asyncio.get_running_loop()
            entered = [asyncio.Event(), asyncio.Event()]
            release = Event()
            checks = []

            class Guard:
                def verify_snapshot(self):
                    checks.append(1)

            app.state.source_guard = Guard()

            def blocked(index):
                loop.call_soon_threadsafe(entered[index].set)
                assert release.wait(2)

            tasks = [
                asyncio.create_task(admission.execute("assembly", lambda i=i: blocked(i)))
                for i in range(2)
            ]
            try:
                await asyncio.gather(*(event.wait() for event in entered))
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client:
                    responses = await asyncio.gather(
                        *[
                            client.get(path)
                            for path in (
                                "/api/v1/persons/suggest",
                                "/api/v1/health",
                                "/api/v1/meta",
                            )
                        ]
                    )
                assert all(response.status_code == 200 for response in responses)
                assert len(checks) == 6, "前后版本检查不能被跳过"
                assert admission.snapshot()["assembly_active"] == 2
            finally:
                release.set()
                await asyncio.gather(*tasks)
            await wait_state(admission, "jobs", 0)
            assert all(value == 0 for value in admission.snapshot().values())

    asyncio.run(scenario())
