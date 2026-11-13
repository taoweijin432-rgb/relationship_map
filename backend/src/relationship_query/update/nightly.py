"""夜间维护、构建独立真实发布、切换和可恢复回退。"""

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from relationship_query.infrastructure.graph_model import read_reader
from relationship_query.infrastructure.real_api import RealGraphBuild
from relationship_query.update.artifacts import checksum, publisher_lock
from relationship_query.update.models import GraphReceipt, UpdateError, UpdateModel, digest
from relationship_query.update.nightly_host import ExpectedRelease, ReleaseHost, SystemdReleaseHost
from relationship_query.update.source_config import MySQLSourceConfig

PREPARED_FILES = {
    "contract.json",
    "source-snapshot.json",
    "input-audit.json",
    "source.sqlite",
    "graph-plan.json",
}
ENV_KEY = "RELATIONSHIP_NUMERIC_RELEASE_STORE"
ENV_PATTERN = re.compile(r"^[ \t]*" + ENV_KEY + r"[ \t]*=([^\r\n]*)", re.MULTILINE)
TERMINAL = {"published", "rolled_back"}


class NightlyConfig(UpdateModel):
    format: Literal["nightly-release-config-v1"] = "nightly-release-config-v1"
    project_directory: Path
    state_directory: Path
    environment_file: Path
    maintenance_file: Path
    prepared_directory: Path
    query_service: str = Field(default="relationship-query.service", pattern=r"^[\w.@-]+\.service$")
    api_base_url: str = "http://127.0.0.1:8000"
    web_base_url: str = "http://127.0.0.1:8088"
    timezone: str = "Asia/Shanghai"
    start_time: str = Field(default="04:30", pattern=r"^\d{2}:\d{2}$")
    maintenance_timeout_seconds: int = Field(default=5400, ge=60)
    build_timeout_seconds: int = Field(default=4800, ge=1)
    startup_timeout_seconds: int = Field(default=180, ge=1)
    service_timeout_seconds: int = Field(default=60, ge=1)
    keep_successful_releases: int = Field(default=2, ge=0)
    source_config_file: Path | None = None
    input_timeout_seconds: int = Field(default=1800, ge=1)
    insecure_source_tls: bool = False

    @model_validator(mode="after")
    def check_configuration(self) -> "NightlyConfig":
        for path in (
            self.project_directory,
            self.state_directory,
            self.environment_file,
            self.maintenance_file,
            self.prepared_directory,
        ):
            if not path.is_absolute() or any(character in str(path) for character in "\r\n\x00"):
                raise ValueError("发布路径须为单行绝对路径")
        for value in (self.api_base_url, self.web_base_url):
            address = urlsplit(value)
            if (
                address.scheme != "http"
                or address.hostname not in {"127.0.0.1", "::1"}
                or address.username
                or address.password
                or address.path not in {"", "/"}
                or address.query
                or address.fragment
            ):
                raise ValueError("验收HTTP入口须为本机loopback根地址")
            _ = address.port
        datetime.strptime(self.start_time, "%H:%M")
        if self.source_config_file is not None and not self.source_config_file.is_absolute():
            raise ValueError("自动采集配置须为绝对路径")
        ZoneInfo(self.timezone)
        if self.recovery_reserve >= self.maintenance_timeout_seconds:
            raise ValueError("维护窗口须覆盖服务恢复预算")
        return self

    @property
    def recovery_reserve(self) -> int:
        return 2 * self.service_timeout_seconds + self.startup_timeout_seconds + 30

    @property
    def binding(self) -> str:
        return digest(
            {
                "project": str(self.project_directory),
                "environment": str(self.environment_file),
                "maintenance": str(self.maintenance_file),
                "service": self.query_service,
                "api": self.api_base_url,
                "web": self.web_base_url,
            }
        )


class NightlyOperation(UpdateModel):
    format: Literal["nightly-release-operation-v1"] = "nightly-release-operation-v1"
    operation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    binding: str
    phase: Literal[
        "prepared",
        "stopping",
        "building",
        "activating",
        "starting",
        "published",
        "rolling_back",
        "rolled_back",
        "recovery_failed",
    ]
    previous_release: Path
    candidate: Path
    backup: Path
    old_environment_digest: str
    new_environment_digest: str
    created_at: str
    error_code: str | None = None


def atomic_file(path: Path, data: bytes, mode: int = 0o600) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".nightly-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def prepared_input(directory: Path) -> dict:
    metadata = json.loads((directory / "prepared.json").read_text())
    if (
        metadata.get("format") != "real-graph-plan-v1"
        or metadata.get("data_mode") != "real"
        or set(metadata.get("files", {})) != PREPARED_FILES
    ):
        raise UpdateError("NIGHTLY_INPUT_INVALID", "夜间构建需要完整的真实冻结输入")
    for name, expected in metadata["files"].items():
        if checksum(directory / name) != expected:
            raise UpdateError("NIGHTLY_INPUT_CHANGED", "真实冻结输入文件摘要不符")
    return metadata


def verified_release(directory: Path) -> tuple[RealGraphBuild, ExpectedRelease]:
    prepared = prepared_input(directory)
    manifest = RealGraphBuild.model_validate_json((directory / "manifest.json").read_text())
    if any(
        prepared[key] != getattr(manifest, key)
        for key in ("version", "source_digest", "reference_month", "sources", "data_mode")
    ):
        raise UpdateError("NIGHTLY_RELEASE_INVALID", "真实候选清单与输入不匹配")
    if prepared.get("person_display", "snapshot") != manifest.person_display:
        raise UpdateError("NIGHTLY_RELEASE_INVALID", "真实候选人物展示模式与输入不匹配")
    receipt = GraphReceipt.model_validate_json((directory / "graph-receipt.json").read_text())
    proofs = manifest.validation.get("independent_sql_proofs", {})
    if (
        manifest.graph != receipt
        or receipt.backend != "nebula"
        or manifest.validation.get("passed") is not True
        or manifest.validation.get("all_graph_rows_verified") is not True
        or set(proofs) != {"same_company", "company_overlap", "same_school", "same_major"}
        or sum(proof["count"] for proof in proofs.values()) != receipt.relation_count
        or sum(prepared["nodes"].values()) != receipt.node_count
        or sum(prepared["facts"].values()) != receipt.fact_count
    ):
        raise UpdateError("NIGHTLY_RELEASE_INVALID", "真实发布缺少完整图及独立SQL核验")
    for name in ("graph/build-resource.json", "graph/reader-credentials.json"):
        if not (directory / name).is_file():
            raise UpdateError("NIGHTLY_RELEASE_INVALID", "真实发布缺少图资源及读取凭据")
    return manifest, ExpectedRelease(
        version=manifest.version,
        person_count=prepared["nodes"]["person"],
        fact_count=receipt.fact_count,
        reference_month=manifest.reference_month,
        person_display=manifest.person_display,
    )


class NightlyPublisher:
    def __init__(self, config: NightlyConfig, host: ReleaseHost | None = None) -> None:
        self.config = config
        self.host = host or SystemdReleaseHost(
            config.project_directory, config.query_service, config.api_base_url, config.web_base_url
        )
        self.journal = config.state_directory / "operation.json"
        self.deadline = float("inf")

    def _environment(self) -> tuple[bytes, Path]:
        content = self.config.environment_file.read_bytes()
        matches = list(ENV_PATTERN.finditer(content.decode()))
        if len(matches) != 1:
            raise UpdateError("NIGHTLY_ENV_INVALID", "查询配置须包含一个明确的发布目录")
        values = shlex.split(matches[0].group(1), comments=True)
        if len(values) != 1:
            raise UpdateError("NIGHTLY_ENV_INVALID", "查询发布目录格式不明确")
        path = Path(values[0])
        return content, (self.config.project_directory / path).resolve()

    @staticmethod
    def _new_environment(content: bytes, directory: Path) -> bytes:
        value = str(directory).replace("\\", "\\\\").replace('"', '\\"')
        replacement = ENV_KEY + '="' + value + '"'
        return ENV_PATTERN.sub(lambda _: replacement, content.decode(), count=1).encode()

    def _load(self) -> NightlyOperation | None:
        if not self.journal.exists():
            return None
        operation = NightlyOperation.model_validate_json(self.journal.read_text())
        if operation.binding != self.config.binding:
            raise UpdateError("NIGHTLY_CONFIG_CHANGED", "未完成任务的服务／路径配置已改变")
        self._operation_directory(operation)
        return operation

    def _operation_directory(self, operation: NightlyOperation) -> Path:
        root = self.config.state_directory.resolve()
        directory = root / "jobs" / operation.operation_id
        if (
            directory.is_symlink()
            or not directory.resolve().is_relative_to(root)
            or operation.backup.resolve() != directory / "query.env.before"
            or operation.candidate.resolve() != directory / "release"
        ):
            raise UpdateError("NIGHTLY_JOURNAL_INVALID", "夜间任务资源路径与状态目录不符")
        return directory

    def _save(self, operation: NightlyOperation, **changes: object) -> NightlyOperation:
        operation = operation.model_copy(update=changes)
        directory = self._operation_directory(operation)
        atomic_file(directory / "operation.json", operation.model_dump_json(indent=2).encode())
        atomic_file(self.journal, operation.model_dump_json(indent=2).encode())
        return operation

    def _remaining(self, maximum: float, *, recovery: bool = False) -> float:
        reserve = 0 if recovery else self.config.recovery_reserve
        remaining = self.deadline - time.monotonic() - reserve
        if remaining <= 0:
            raise UpdateError("NIGHTLY_WINDOW_TIMEOUT", "维护窗口已达到预留恢复的截止点")
        return min(maximum, remaining)

    def _marker(self, operation: NightlyOperation, *, remove: bool = False) -> None:
        path = self.config.maintenance_file
        if path.exists():
            owner = json.loads(path.read_text())
            if owner.get("operation_id") != operation.operation_id:
                raise UpdateError("NIGHTLY_MARKER_OWNED", "维护标记属于其他操作")
        if remove:
            path.unlink(missing_ok=True)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        else:
            atomic_file(path, json.dumps({"operation_id": operation.operation_id}).encode())

    def plan(self, prepared: Path | None = None) -> dict:
        source = (prepared or self._latest_input()).resolve()
        _, previous = self._environment()
        old, _ = verified_release(previous)
        candidate = prepared_input(source)
        if candidate["reference_month"] < old.reference_month:
            raise UpdateError("REFERENCE_MONTH", "夜间更新候选基准月早于当前发布")
        return {
            "status": "up_to_date"
            if (
                candidate["version"] == old.version
                and candidate["source_digest"] == old.source_digest
                and candidate["reference_month"] == old.reference_month
                and self._source_identities(candidate["sources"])
                == self._source_identities(old.sources)
                and candidate.get("person_display", "snapshot") == old.person_display
            )
            else "update_available",
            "previous_release": str(previous),
            "prepared": str(source),
            "previous_version": old.version,
            "candidate_version": candidate["version"],
            "timezone": self.config.timezone,
            "start_time": self.config.start_time,
            "maintenance_timeout_seconds": self.config.maintenance_timeout_seconds,
        }

    def _latest_input(self) -> Path:
        pointer = self.config.state_directory / "input.json"
        if self.config.source_config_file is None or not pointer.exists():
            return self.config.prepared_directory
        selected = Path(json.loads(pointer.read_text())["prepared"])
        if not selected.resolve().is_relative_to(
            (self.config.state_directory / "inputs").resolve()
        ):
            raise UpdateError("NIGHTLY_INPUT_INVALID", "自动采集输入路径超出本程序目录")
        return selected

    def _fresh_input(self) -> Path:
        source_file = self.config.source_config_file
        assert source_file is not None
        config = MySQLSourceConfig.read(source_file)
        for role in ("entities", "people"):
            endpoint = config.endpoint(role)  # type: ignore[arg-type]
            if not os.environ.get(endpoint.password_env or ""):
                raise UpdateError("NIGHTLY_SOURCE_CREDENTIALS", "自动采集需要已配置的密码环境变量")
        root = self.config.state_directory / "inputs"
        root.mkdir(mode=0o700, exist_ok=True)
        directory = root / uuid4().hex
        directory.mkdir(mode=0o700)
        atomic_file(directory / "input.json", b'{"format":"nightly-input-v1"}')
        now = datetime.now(ZoneInfo(self.config.timezone))
        try:
            self.host.prepare_input(
                directory,
                source_file,
                now.year * 100 + now.month,
                self.config.insecure_source_tls,
                self._remaining(self.config.input_timeout_seconds),
            )
            prepared = directory / "prepared"
            metadata = prepared_input(prepared)
            if metadata.get("person_display") != "mysql-live":
                raise UpdateError("NIGHTLY_INPUT_INVALID", "自动输入需要在线人物展示模式")
            atomic_file(
                self.config.state_directory / "input.json",
                json.dumps(
                    {
                        "prepared": str(prepared),
                        "version": metadata["version"],
                        "captured_at": now.isoformat(),
                    }
                ).encode(),
            )
            return prepared
        finally:
            try:
                self._prune_inputs(root)
            except (OSError, ValueError, UpdateError):
                atomic_file(
                    self.config.state_directory / "input-cleanup.json",
                    b'{"status":"pending","code":"NIGHTLY_INPUT_CLEANUP"}',
                )

    def _prune_inputs(self, root: Path) -> None:
        owned = sorted(
            (
                path
                for path in root.iterdir()
                if re.fullmatch(r"[0-9a-f]{32}", path.name)
                and not path.is_symlink()
                and (path / "input.json").is_file()
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        current = self._latest_input().parent.resolve()
        # 保留最近两次采集及当前选中的输入，失败重试期间仍可核对上一份完整输入。
        for path in owned[2:]:
            if path.resolve() == current:
                continue
            if json.loads((path / "input.json").read_text()).get("format") == "nightly-input-v1":
                shutil.rmtree(path)

    @staticmethod
    def _source_identities(sources: list[dict]) -> list[tuple]:
        return [
            (
                source.get("host"),
                source.get("port"),
                source.get("database"),
                source.get("server", {}).get("server_uuid"),
            )
            for source in sources
        ]

    def _window(self, scheduled: bool) -> bool:
        duration = self.config.maintenance_timeout_seconds
        if scheduled:
            now = datetime.now(ZoneInfo(self.config.timezone))
            hour, minute = map(int, self.config.start_time.split(":"))
            start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now < start:
                start -= timedelta(days=1)
            end = start + timedelta(seconds=duration)
            if not start <= now < end:
                return False
            duration = min(duration, int((end - now).total_seconds()))
            if duration <= self.config.recovery_reserve:
                return False
        self.deadline = time.monotonic() + duration
        return True

    def run(self, prepared: Path | None = None, *, scheduled: bool = False) -> dict:
        self.config.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with publisher_lock(self.config.state_directory):
            pending = self._load()
            if pending is not None and pending.phase not in TERMINAL:
                return self._recover(pending)
            if not self._window(scheduled):
                return {"status": "outside_window"}
            if self.config.source_config_file is not None and prepared is None:
                prepared = self._fresh_input()
            plan = self.plan(prepared)
            if plan["status"] == "up_to_date":
                return plan
            if self.config.maintenance_file.exists():
                raise UpdateError("NIGHTLY_ALREADY_MAINTAINED", "已有维护标记，请先核对维护状态")
            if not self.host.active(self.config.service_timeout_seconds):
                raise UpdateError("NIGHTLY_SERVICE_INACTIVE", "查询服务当前未运行，保持现有状态")
            operation = self._prepare_operation(Path(plan["prepared"]))
            return self._with_cleanup(self._publish(operation))

    def prepare_input(self) -> dict:
        if self.config.source_config_file is None:
            raise UpdateError("NIGHTLY_SOURCE_CONFIG", "请先配置自动采集来源")
        self.config.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with publisher_lock(self.config.state_directory):
            pending = self._load()
            if pending is not None and pending.phase not in TERMINAL:
                raise UpdateError("NIGHTLY_RECOVERY_REQUIRED", "未完成发布需先恢复")
            source = self._fresh_input()
            metadata = prepared_input(source)
            return {
                "status": "input_prepared",
                "plan": self.plan(source),
                "nodes": metadata["nodes"],
                "facts": metadata["facts"],
            }

    def _prepare_operation(self, source: Path) -> NightlyOperation:
        content, previous = self._environment()
        _, expected = verified_release(previous)
        self.host.ready(expected, self._remaining(self.config.startup_timeout_seconds))
        operation_id = uuid4().hex
        directory = self.config.state_directory / "jobs" / operation_id
        candidate = directory / "release"
        candidate.mkdir(parents=True, mode=0o700)
        directory.chmod(0o700)
        metadata = prepared_input(source)
        for name in sorted(PREPARED_FILES | {"prepared.json"}):
            shutil.copyfile(source / name, candidate / name)
            (candidate / name).chmod(0o600)
        if prepared_input(candidate) != metadata:
            raise UpdateError("NIGHTLY_INPUT_CHANGED", "冻结输入在准备期间发生变化")
        backup = directory / "query.env.before"
        atomic_file(backup, content)
        new_content = self._new_environment(content, candidate)
        operation = NightlyOperation(
            operation_id=operation_id,
            binding=self.config.binding,
            phase="prepared",
            previous_release=previous,
            candidate=candidate,
            backup=backup,
            old_environment_digest=checksum(backup),
            new_environment_digest=digest(new_content.decode()),
            created_at=datetime.now(ZoneInfo(self.config.timezone)).isoformat(),
        )
        self._remaining(1)
        return self._save(operation)

    def _publish(self, operation: NightlyOperation) -> dict:
        try:
            self._marker(operation)
            self.host.maintenance_ready(self._remaining(10))
            operation = self._save(operation, phase="stopping")
            self.host.service("stop", self._remaining(self.config.service_timeout_seconds))
            operation = self._save(operation, phase="building")
            self.host.build(
                operation.candidate,
                operation.candidate.parent / "build.log",
                self._remaining(self.config.build_timeout_seconds),
            )
            _, expected = verified_release(operation.candidate)
            operation = self._save(operation, phase="activating")
            self._set_environment(operation, candidate=True)
            operation = self._save(operation, phase="starting")
            self.host.service("start", self._remaining(self.config.service_timeout_seconds))
            self.host.ready(expected, self._remaining(self.config.startup_timeout_seconds))
            self._marker(operation, remove=True)
            self._save(operation, phase="published")
            return {
                "status": "published",
                "version": expected.version,
                "release": str(operation.candidate),
            }
        except Exception as error:
            operation = self._save(
                operation, error_code=getattr(error, "code", type(error).__name__)
            )
            self._recover(operation)
            raise UpdateError(
                "NIGHTLY_UPDATE_FAILED", "夜间更新失败，上一完整发布已恢复，请检查任务日志"
            ) from None

    def _set_environment(self, operation: NightlyOperation, *, candidate: bool) -> None:
        old = operation.backup.read_bytes()
        if checksum(operation.backup) != operation.old_environment_digest:
            raise UpdateError("NIGHTLY_BACKUP_CHANGED", "原查询配置备份摘要变化")
        new = self._new_environment(old, operation.candidate)
        if digest(new.decode()) != operation.new_environment_digest:
            raise UpdateError("NIGHTLY_BACKUP_CHANGED", "目标查询配置与任务不符")
        current = self.config.environment_file.read_bytes()
        if current not in (old, new):
            raise UpdateError("NIGHTLY_ENV_CHANGED", "查询配置已被其他操作修改，请核对后恢复")
        mode = stat.S_IMODE(self.config.environment_file.stat().st_mode)
        atomic_file(self.config.environment_file, new if candidate else old, mode)

    def _recover(self, operation: NightlyOperation) -> dict:
        original_phase = operation.phase
        try:
            operation = self._save(operation, phase="rolling_back")
            self._marker(operation)
            _, expected = verified_release(operation.previous_release)
            if original_phase != "prepared" or not self.host.active(
                self._remaining(self.config.service_timeout_seconds, recovery=True)
            ):
                self.host.service(
                    "stop", self._remaining(self.config.service_timeout_seconds, recovery=True)
                )
                self._set_environment(operation, candidate=False)
                self.host.service(
                    "start", self._remaining(self.config.service_timeout_seconds, recovery=True)
                )
            self.host.ready(
                expected, self._remaining(self.config.startup_timeout_seconds, recovery=True)
            )
            self._marker(operation, remove=True)
            self._save(operation, phase="rolled_back")
            return {"status": "rolled_back", "version": expected.version}
        except Exception as error:
            self._save(
                operation,
                phase="recovery_failed",
                error_code=getattr(error, "code", type(error).__name__),
            )
            raise UpdateError(
                "NIGHTLY_RECOVERY_FAILED", "恢复未完成，维护状态已保留，请读取任务记录"
            ) from None

    def recover(self) -> dict:
        if not self.config.state_directory.exists():
            return {"status": "idle"}
        with publisher_lock(self.config.state_directory):
            operation = self._load()
            if operation is None:
                return {"status": "idle"}
            if operation.phase in TERMINAL:
                if self.config.maintenance_file.exists():
                    release = (
                        operation.candidate
                        if operation.phase == "published"
                        else operation.previous_release
                    )
                    _, expected = verified_release(release)
                    self.host.ready(expected, self.config.startup_timeout_seconds)
                    self._marker(operation, remove=True)
                return self._with_cleanup({"status": "idle"})
            return self._with_cleanup(self._recover(operation))

    def _with_cleanup(self, result: dict) -> dict:
        try:
            cleanup = self._prune()
        except Exception as error:
            # 发布或恢复已经完成，资源清理失败单独登记并由下次运行重试。
            cleanup = {"status": "pending", "code": getattr(error, "code", type(error).__name__)}
        atomic_file(self.config.state_directory / "cleanup.json", json.dumps(cleanup).encode())
        return {**result, "cleanup": cleanup}

    def _prune(self) -> dict:
        current = self._load()
        if current is None:
            return {"status": "cleaned", "removed": 0}
        if current.phase not in TERMINAL:
            raise UpdateError("NIGHTLY_RECOVERY_REQUIRED", "未完成的夜间任务需先恢复")
        _, active = self._environment()
        protected = {
            active,
            current.previous_release.resolve(),
            current.candidate.resolve(),
            self.config.prepared_directory.resolve(),
        }
        records = []
        for path in self.config.state_directory.glob("jobs/*/operation.json"):
            record = NightlyOperation.model_validate_json(path.read_text())
            if record.binding != self.config.binding or record.phase not in TERMINAL:
                continue
            directory = self._operation_directory(record)
            if path.parent.resolve() != directory:
                raise UpdateError("NIGHTLY_JOURNAL_INVALID", "历史任务记录与资源目录不符")
            if record.candidate.exists():
                records.append(record)
        successful = sorted(
            (record for record in records if record.phase == "published"),
            key=lambda record: datetime.fromisoformat(record.created_at),
            reverse=True,
        )
        protected.update(
            record.candidate.resolve()
            for record in successful[: self.config.keep_successful_releases]
        )
        protected_resources = [self._resources(path) for path in protected]
        removed = 0
        for record in records:
            if record.candidate.resolve() in protected:
                continue
            space, account = self._resources(record.candidate)
            if any(
                space is not None
                and space == protected_space
                or account is not None
                and account == protected_account
                for protected_space, protected_account in protected_resources
            ):
                raise UpdateError("NIGHTLY_CLEANUP_PROTECTED", "历史资源与保留发布共享图或账号")
            if space is not None:
                self.host.remove_graph(space, account)
            shutil.rmtree(record.candidate)
            removed += 1
        return {"status": "cleaned", "removed": removed}

    @staticmethod
    def _resources(directory: Path) -> tuple[str | None, str | None]:
        marker = directory / "graph/build-resource.json"
        if not marker.exists():
            return None, None
        resource = json.loads(marker.read_text())
        space = resource["space"]
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            manifest = RealGraphBuild.model_validate_json(manifest_path.read_text())
            if manifest.graph.space != space:
                raise UpdateError("NIGHTLY_CLEANUP_INVALID", "历史图空间与发布清单不符")
        account = None
        if (directory / "graph/reader-credentials.json").exists():
            account = read_reader(marker).username
        return space, account

    def prune(self) -> dict:
        if not self.config.state_directory.exists():
            return {"status": "cleaned", "removed": 0}
        with publisher_lock(self.config.state_directory):
            return self._prune()

    def status(self) -> dict:
        operation = self._load()
        return {"status": "idle"} if operation is None else operation.model_dump(mode="json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["plan", "run", "recover", "status", "prune", "prepare-input"]
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--scheduled", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = NightlyConfig.model_validate_json(args.config.read_text())
        publisher = NightlyPublisher(config)
        if args.command == "run":
            result = publisher.run(args.prepared, scheduled=args.scheduled)
        elif args.command == "plan":
            result = publisher.plan(args.prepared)
        elif args.command == "recover":
            result = publisher.recover()
        elif args.command == "prune":
            result = publisher.prune()
        elif args.command == "prepare-input":
            result = publisher.prepare_input()
        else:
            result = publisher.status()
    except UpdateError as error:
        print(
            json.dumps({"ok": False, "code": error.code, "message": str(error)}, ensure_ascii=False)
        )
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "NIGHTLY_INVALID_INPUT",
                    "message": "夜间配置或发布文件读取／校验失败",
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
