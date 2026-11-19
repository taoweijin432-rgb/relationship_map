"""夜间发布的systemd、构建子进程与本机HTTP适配。"""

import re
import subprocess
import time
from pathlib import Path
from typing import Literal, Protocol

import httpx
from pydantic import Field

from relationship_query.update.models import UpdateError, UpdateModel


class ExpectedRelease(UpdateModel):
    version: str
    person_count: int = Field(ge=0)
    fact_count: int = Field(ge=0)
    reference_month: int
    person_display: Literal["snapshot", "mysql-live"] = "snapshot"


class ReleaseHost(Protocol):
    def prepare_input(
        self, directory: Path, config: Path, month: int, insecure: bool, timeout: float
    ) -> None: ...
    def active(self, timeout: float) -> bool: ...
    def service(self, action: str, timeout: float) -> None: ...
    def maintenance_ready(self, timeout: float) -> None: ...
    def build(
        self, directory: Path, log: Path, timeout: float, *, build_member_index: bool = False
    ) -> None: ...
    def ready(self, expected: ExpectedRelease, timeout: float) -> None: ...
    def remove_graph(self, space: str, account: str | None) -> None: ...


class SystemdReleaseHost:
    def __init__(self, project: Path, service: str, api_url: str, web_url: str) -> None:
        self.project, self.name = project, service
        self.api_url, self.web_url = api_url.rstrip("/"), web_url.rstrip("/")

    def _systemctl(self, action: str, timeout: float) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                ["systemctl", action, self.name],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise UpdateError("NIGHTLY_SERVICE_ERROR", "查询服务操作失败或超时") from None

    def active(self, timeout: float) -> bool:
        result = self._systemctl("is-active", timeout)
        if result.returncode not in (0, 3):
            raise UpdateError("NIGHTLY_SERVICE_ERROR", "查询服务状态读取失败")
        return result.returncode == 0

    def service(self, action: str, timeout: float) -> None:
        if action not in {"start", "stop"}:
            raise ValueError("不支持的查询服务操作")
        if self._systemctl(action, timeout).returncode:
            raise UpdateError("NIGHTLY_SERVICE_ERROR", "查询服务操作返回失败")

    def maintenance_ready(self, timeout: float) -> None:
        try:
            with httpx.Client(trust_env=False, timeout=timeout) as client:
                page = client.get(self.web_url + "/")
                api = client.get(self.web_url + "/api/v1/health")
            if page.status_code != 503 or api.status_code != 503:
                raise ValueError("maintenance response")
            if api.json().get("code") != "MAINTENANCE":
                raise ValueError("maintenance code")
        except (httpx.HTTPError, ValueError, AttributeError):
            raise UpdateError(
                "NIGHTLY_MAINTENANCE_GATE", "页面及API维护响应未就绪，请核对Nginx配置"
            ) from None

    def prepare_input(
        self, directory: Path, config: Path, month: int, insecure: bool, timeout: float
    ) -> None:
        python = str(self.project / "backend/.venv/bin/python")
        capture = [
            python,
            str(self.project / "scripts/capture_real_graph_sources.py"),
            "--source-config",
            str(config),
            "--output",
            str(directory / "capture"),
            "--relation-only",
        ]
        if insecure:
            capture.append("--insecure-tls")
        prepare = [
            python,
            str(self.project / "scripts/build_real_graph.py"),
            "--input",
            str(directory / "capture"),
            "--output",
            str(directory / "prepared"),
            "--reference-month",
            str(month),
            "--prepare-only",
        ]
        log = directory / "input.log"
        log.touch(mode=0o600, exist_ok=False)
        deadline = time.monotonic() + timeout
        try:
            with log.open("wb") as stream:
                for command in (capture, prepare):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    subprocess.run(
                        command,
                        cwd=self.project,
                        stdin=subprocess.DEVNULL,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        check=True,
                        timeout=remaining,
                    )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise UpdateError(
                "NIGHTLY_INPUT_FAILED", "自动采集或输入准备失败，请读取私有input.log"
            ) from None

    def build(
        self, directory: Path, log: Path, timeout: float, *, build_member_index: bool = False
    ) -> None:
        command = [
            str(self.project / "backend/.venv/bin/python"),
            str(self.project / "scripts/build_real_graph.py"),
            "--output",
            str(directory),
            "--build-prepared",
        ]
        if build_member_index:
            command.append("--build-member-index")
        log.touch(mode=0o600, exist_ok=False)
        try:
            with log.open("wb") as stream:
                subprocess.run(
                    command,
                    cwd=self.project,
                    stdin=subprocess.DEVNULL,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=timeout,
                )
        except subprocess.TimeoutExpired:
            raise UpdateError("NIGHTLY_BUILD_TIMEOUT", "候选图构建达到时间预算") from None
        except (OSError, subprocess.CalledProcessError):
            raise UpdateError(
                "NIGHTLY_BUILD_FAILED", "候选图构建失败，请读取私有构建日志"
            ) from None

    def remove_graph(self, space: str, account: str | None) -> None:
        from relationship_query.infrastructure.nebula_lab import connect, load_credentials, query

        if not re.fullmatch(r"relationship_lab_sync_[0-9a-f]{12}", space) or (
            account is not None and not re.fullmatch(r"rq_[0-9a-f]{12}", account)
        ):
            raise UpdateError("NIGHTLY_CLEANUP_INVALID", "待清理资源名称与构建格式不符")
        credentials = self.project / "data/nebula-lab/credentials.json"
        with connect(load_credentials(credentials)) as session:
            query(session, f"DROP SPACE IF EXISTS `{space}`")
            if account is not None:
                query(session, f"DROP USER IF EXISTS {account}")
            if any(row["Name"] == space for row in query(session, "SHOW SPACES")):
                raise UpdateError("NIGHTLY_CLEANUP_PENDING", "旧图空间清理尚未确认")

    def ready(self, expected: ExpectedRelease, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        with httpx.Client(trust_env=False) as client:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    health = client.get(self.api_url + "/api/v1/health", timeout=min(3, remaining))
                    health.raise_for_status()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    meta = client.get(self.api_url + "/api/v1/meta", timeout=min(3, remaining))
                    meta.raise_for_status()
                    try:
                        self._check_ready(health.json(), meta.json(), expected)
                    except (ValueError, AttributeError):
                        raise UpdateError(
                            "NIGHTLY_HEALTH_MISMATCH", "查询服务验收响应格式不符"
                        ) from None
                    return
                except httpx.HTTPError:
                    time.sleep(max(0, min(1, deadline - time.monotonic())))
        raise UpdateError("NIGHTLY_STARTUP_TIMEOUT", "查询服务在预算内未完成启动核验")

    @staticmethod
    def _check_ready(health: dict, meta: dict, expected: ExpectedRelease) -> None:
        if (
            (expected.person_display == "mysql-live" and meta.get("person_display") != "mysql-live")
            or health.get("status") != "ok"
            or health.get("data_mode") != "real"
            or health.get("data_version") != expected.version
            or any(
                meta.get(key) != value
                for key, value in {
                    "data_mode": "real",
                    "data_version": expected.version,
                    "person_count": expected.person_count,
                    "fact_count": expected.fact_count,
                    "reference_month": expected.reference_month,
                    "relation_backend": "nebula-materialized",
                }.items()
            )
        ):
            raise UpdateError("NIGHTLY_HEALTH_MISMATCH", "查询服务实际数据与目标发布不符")
