"""真实构建子进程及HTTP适配边界，systemd操作使用命令替身。"""

import subprocess
import sys

import httpx
import pytest

from relationship_query.update import nightly_host
from relationship_query.update.models import UpdateError
from relationship_query.update.nightly_host import ExpectedRelease, SystemdReleaseHost


@pytest.fixture
def host(tmp_path):
    return SystemdReleaseHost(
        tmp_path, "relationship-query.service", "http://127.0.0.1:8000", "http://127.0.0.1:8088"
    )


def client_transport(monkeypatch, handler):
    client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        nightly_host.httpx, "Client", lambda **kwargs: client(transport=transport, **kwargs)
    )


@pytest.mark.parametrize("bad", [None, "page", "api", "code"])
def test_maintenance_probes_both_page_and_api(host, monkeypatch, bad):
    called = []

    def respond(request):
        called.append(str(request.url))
        if request.url.path == "/":
            return httpx.Response(200 if bad == "page" else 503, text="maintenance")
        return httpx.Response(
            200 if bad == "api" else 503,
            json={"code": "OTHER" if bad == "code" else "MAINTENANCE"},
        )

    client_transport(monkeypatch, respond)
    if bad:
        with pytest.raises(UpdateError, match="维护响应"):
            host.maintenance_ready(2)
    else:
        host.maintenance_ready(2)
    assert called == ["http://127.0.0.1:8088/", "http://127.0.0.1:8088/api/v1/health"]


def responses(expected):
    return {
        "/api/v1/health": {"status": "ok", "data_mode": "real", "data_version": expected.version},
        "/api/v1/meta": {
            "data_mode": "real",
            "data_version": expected.version,
            "person_count": expected.person_count,
            "fact_count": expected.fact_count,
            "reference_month": expected.reference_month,
            "relation_backend": "nebula-materialized",
        },
    }


@pytest.mark.parametrize("failure", [None, "version", "count", "json"])
def test_readiness_validates_actual_version_and_counts(host, monkeypatch, failure):
    expected = ExpectedRelease(
        version="real-test", person_count=2, fact_count=6, reference_month=202611
    )
    body = responses(expected)
    if failure == "version":
        body["/api/v1/health"]["data_version"] = "wrong"
    if failure == "count":
        body["/api/v1/meta"]["person_count"] = 3

    def respond(request):
        if failure == "json":
            return httpx.Response(200, text="invalid JSON")
        return httpx.Response(200, json=body[request.url.path])

    client_transport(monkeypatch, respond)
    if failure:
        with pytest.raises(UpdateError) as error:
            host.ready(expected, 1)
        assert error.value.code == "NIGHTLY_HEALTH_MISMATCH"
    else:
        host.ready(expected, 1)


def test_readiness_retries_connection_errors_and_honors_timeout(host, monkeypatch):
    expected = ExpectedRelease(
        version="real-test", person_count=2, fact_count=6, reference_month=202611
    )
    clock = [0.0]
    monkeypatch.setattr(nightly_host.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        nightly_host.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration)
    )

    def respond(request):
        raise httpx.ConnectError("not ready", request=request)

    client_transport(monkeypatch, respond)
    with pytest.raises(UpdateError) as error:
        host.ready(expected, 2)
    assert error.value.code == "NIGHTLY_STARTUP_TIMEOUT" and clock[0] == 2


@pytest.mark.parametrize("result,expected", [(0, True), (3, False), (4, None)])
def test_systemd_command_scope_and_status(host, monkeypatch, result, expected):
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, result)

    monkeypatch.setattr(nightly_host.subprocess, "run", execute)
    if expected is None:
        with pytest.raises(UpdateError):
            host.active(5)
    else:
        assert host.active(5) is expected
    assert calls[0][0] == ["systemctl", "is-active", "relationship-query.service"]
    assert calls[0][1]["timeout"] == 5 and "shell" not in calls[0][1]


@pytest.mark.parametrize(
    "behavior,error",
    [("success", None), ("failure", "NIGHTLY_BUILD_FAILED"), ("timeout", "NIGHTLY_BUILD_TIMEOUT")],
)
@pytest.mark.parametrize("indexed", [False, True])
def test_real_build_subprocess_logging_failure_and_timeout(
    host, tmp_path, behavior, error, indexed
):
    python = tmp_path / "backend/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    script = tmp_path / "scripts/build_real_graph.py"
    script.parent.mkdir()
    contents = {
        "success": "import sys\nprint('--build-member-index' in sys.argv)\n",
        "failure": "raise SystemExit(7)\n",
        "timeout": "import time\ntime.sleep(60)\n",
    }
    script.write_text(contents[behavior])
    log = tmp_path / "build.log"
    if error:
        with pytest.raises(UpdateError) as caught:
            host.build(
                tmp_path / "candidate",
                log,
                0.05 if behavior == "timeout" else 3,
                build_member_index=indexed,
            )
        assert caught.value.code == error
    else:
        host.build(tmp_path / "candidate", log, 3, build_member_index=indexed)
        assert log.read_text().strip() == str(indexed)
    assert log.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "space,account", [("other_space", None), ("relationship_lab_sync_0123456789ab", "root")]
)
def test_cleanup_rejects_unmanaged_resource_names(host, space, account):
    with pytest.raises(UpdateError) as error:
        host.remove_graph(space, account)
    assert error.value.code == "NIGHTLY_CLEANUP_INVALID"
