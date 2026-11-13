"""夜间发布状态机。真实SQL文件配合图／systemd替身，覆盖切换与恢复。"""

import json
import shlex
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from relationship_query.infrastructure.real_api import RealGraphRepository
from relationship_query.update import nightly
from relationship_query.update.artifacts import checksum, publisher_lock
from relationship_query.update.models import UpdateError
from relationship_query.update.nightly import (
    ENV_KEY,
    ENV_PATTERN,
    PREPARED_FILES,
    NightlyConfig,
    NightlyPublisher,
    verified_release,
)

from .test_real_query import real_release as real_release


def save_json(path, value):
    path.write_text(json.dumps(value))


class FakeHost:
    def __init__(self, config, previous):
        self.config, self.previous = config, previous
        self.running = True
        self.loaded = previous
        self.calls = []
        self.fail = None
        self.crash = None
        self.after_build = lambda: None
        self.removed = []

    def active(self, timeout):
        return self.running

    def service(self, action, timeout):
        self.calls.append(action)
        assert self.config.maintenance_file.exists()
        assert timeout > 0
        if action == "stop":
            self.running = False
            return
        content = self.config.environment_file.read_text()
        self.loaded = Path(shlex.split(ENV_PATTERN.search(content).group(1))[0])
        kind = "start_old" if self.loaded == self.previous else "start_new"
        if self.fail == kind:
            raise UpdateError("TEST_START_FAILURE", kind)
        self.running = True

    def maintenance_ready(self, timeout):
        self.calls.append("maintenance")
        assert self.config.maintenance_file.exists()
        if self.fail == "maintenance":
            raise UpdateError("TEST_GATE_FAILURE", "gate")

    def build(self, directory, log, timeout):
        self.calls.append("build")
        assert not self.running
        assert 0 < timeout <= self.config.build_timeout_seconds
        log.write_text("fictional build log")
        if self.crash == "build":
            raise KeyboardInterrupt()
        if self.fail == "build":
            raise UpdateError("TEST_BUILD_FAILURE", "build")
        metadata = json.loads((directory / "prepared.json").read_text())
        manifest = json.loads((self.previous / "manifest.json").read_text())
        for key in ("version", "source_digest", "reference_month", "sources", "data_mode"):
            manifest[key] = metadata[key]
        shutil.copytree(self.previous / "graph", directory / "graph")
        receipt = json.loads((self.previous / "graph-receipt.json").read_text())
        receipt["space"] = "relationship_lab_sync_" + directory.parent.name[:12]
        manifest["graph"] = receipt
        save_json(directory / "graph-receipt.json", receipt)
        save_json(directory / "graph/build-resource.json", {"space": receipt["space"]})
        reader = json.loads((directory / "graph/reader-credentials.json").read_text())
        reader["username"] = "rq_" + directory.parent.name[:12]
        save_json(directory / "graph/reader-credentials.json", reader)
        save_json(directory / "manifest.json", manifest)
        self.after_build()

    def ready(self, expected, timeout):
        assert self.running
        assert timeout > 0
        kind = "old" if self.loaded == self.previous else "new"
        self.calls.append("ready_" + kind)
        if self.crash == "ready_" + kind:
            raise KeyboardInterrupt()
        if self.fail == "ready_" + kind:
            raise UpdateError("TEST_READY_FAILURE", kind)
        manifest, actual = verified_release(self.loaded)
        assert actual == expected
        # SQL文件和版本仍由真正仓储校验，图完整回读留给原生集成验收。
        repository = RealGraphRepository(self.loaded)
        try:
            assert repository.version == manifest.version
        finally:
            repository.engine.dispose()

    def remove_graph(self, space, account):
        self.removed.append((space, account))


@pytest.fixture
def case(real_release):
    entries = list(real_release.iterdir())
    previous = real_release / "previous"
    previous.mkdir()
    for entry in entries:
        shutil.move(str(entry), previous / entry.name)
    manifest = json.loads((previous / "manifest.json").read_text())
    manifest["validation"]["all_graph_rows_verified"] = True
    save_json(previous / "manifest.json", manifest)
    metadata = json.loads((previous / "prepared.json").read_text())
    metadata.update(relation_upper_bound=100, quarantine={}, zero_dates_to_null=0)
    save_json(previous / "prepared.json", metadata)
    prepared = real_release / "prepared"
    prepared.mkdir()
    for name in PREPARED_FILES | {"prepared.json"}:
        shutil.copyfile(previous / name, prepared / name)
    with sqlite3.connect(prepared / "source.sqlite") as connection:
        connection.execute(
            "UPDATE demo_dataset SET version=?,reference_month=?", ("nightly-next", 202612)
        )
    metadata.update(version="nightly-next", reference_month=202612)
    metadata["files"]["source.sqlite"] = checksum(prepared / "source.sqlite")
    save_json(prepared / "prepared.json", metadata)
    environment = real_release / "query.env"
    original = (f"# query environment\n{ENV_KEY}={previous}\nPYTHONUNBUFFERED=1\n").encode()
    environment.write_bytes(original)
    environment.chmod(0o600)
    config = NightlyConfig(
        project_directory=real_release,
        state_directory=real_release / "nightly",
        environment_file=environment,
        maintenance_file=real_release / "maintenance.flag",
        prepared_directory=prepared,
    )
    host = FakeHost(config, previous)
    return SimpleNamespace(
        config=config,
        host=host,
        publisher=NightlyPublisher(config, host),
        previous=previous,
        prepared=prepared,
        original=original,
    )


def test_plan_and_cli_are_readonly(case, tmp_path, capsys):
    plan = case.publisher.plan()
    assert plan["status"] == "update_available"
    assert plan["start_time"] == "04:30" and plan["maintenance_timeout_seconds"] == 5400
    assert not case.config.state_directory.exists()
    path = tmp_path / "nightly.json"
    path.write_text(case.config.model_dump_json())
    assert nightly.main(["plan", "--config", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["candidate_version"] == "nightly-next"
    assert case.host.calls == []


def test_publish_stops_builds_switches_checks_and_reopens(case):
    result = case.publisher.run()
    assert result["status"] == "published" and result["version"] == "nightly-next"
    assert case.host.calls == ["ready_old", "maintenance", "stop", "build", "start", "ready_new"]
    assert case.host.running and not case.config.maintenance_file.exists()
    assert case.publisher.status()["phase"] == "published"
    assert "PYTHONUNBUFFERED=1" in case.config.environment_file.read_text()
    assert case.config.environment_file.stat().st_mode & 0o777 == 0o600
    assert (case.previous / "manifest.json").exists()
    assert case.publisher.recover()["status"] == "idle"
    assert case.publisher.plan()["status"] == "up_to_date"


def test_same_input_skips_before_maintenance(case):
    result = case.publisher.run(case.previous)
    assert result["status"] == "up_to_date" and case.host.calls == []
    assert not case.config.maintenance_file.exists()


@pytest.mark.parametrize("failure", ["build", "start_new", "ready_new"])
def test_failure_restores_exact_old_configuration_and_service(case, failure):
    case.host.fail = failure
    with pytest.raises(UpdateError) as error:
        case.publisher.run()
    assert error.value.code == "NIGHTLY_UPDATE_FAILED"
    assert case.config.environment_file.read_bytes() == case.original
    assert case.host.loaded == case.previous and case.host.running
    assert not case.config.maintenance_file.exists()
    assert case.publisher.status()["phase"] == "rolled_back"


def test_bad_nginx_gate_leaves_existing_api_running(case):
    case.host.fail = "maintenance"
    with pytest.raises(UpdateError):
        case.publisher.run()
    assert "stop" not in case.host.calls and "build" not in case.host.calls
    assert case.host.running and not case.config.maintenance_file.exists()


@pytest.mark.parametrize("phase", ["build", "ready_new"])
def test_interrupted_operation_recovers_after_restart(case, phase):
    case.host.crash = phase
    with pytest.raises(KeyboardInterrupt):
        case.publisher.run()
    assert case.config.maintenance_file.exists()
    case.host.crash = None
    restarted = NightlyPublisher(case.config, case.host)
    assert restarted.recover()["status"] == "rolled_back"
    assert case.host.loaded == case.previous and case.host.running
    assert case.config.environment_file.read_bytes() == case.original
    assert not case.config.maintenance_file.exists()


def test_run_first_recovers_pending_operation(case):
    case.host.crash = "build"
    with pytest.raises(KeyboardInterrupt):
        case.publisher.run()
    case.host.crash = None
    before = case.host.calls.count("build")
    assert NightlyPublisher(case.config, case.host).run()["status"] == "rolled_back"
    assert case.host.calls.count("build") == before


def test_recovery_failure_keeps_durable_maintenance_state(case):
    case.host.crash = "ready_new"
    with pytest.raises(KeyboardInterrupt):
        case.publisher.run()
    case.host.crash, case.host.fail = None, "start_old"
    restarted = NightlyPublisher(case.config, case.host)
    with pytest.raises(UpdateError) as error:
        restarted.recover()
    assert error.value.code == "NIGHTLY_RECOVERY_FAILED"
    assert restarted.status()["phase"] == "recovery_failed"
    assert case.config.maintenance_file.exists()
    case.host.fail = None
    assert restarted.recover()["status"] == "rolled_back"


def test_foreign_configuration_changes_are_preserved(case):
    changed = case.original + b"MANUAL_CHANGE=1\n"
    case.host.after_build = lambda: case.config.environment_file.write_bytes(changed)
    with pytest.raises(UpdateError) as error:
        case.publisher.run()
    assert error.value.code == "NIGHTLY_RECOVERY_FAILED"
    assert case.config.environment_file.read_bytes() == changed
    assert case.config.maintenance_file.exists()


def test_window_reserves_time_for_rollback(case, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(nightly.time, "monotonic", lambda: clock[0])
    case.host.after_build = lambda: clock.__setitem__(
        0, case.publisher.deadline - case.config.recovery_reserve + 1
    )
    with pytest.raises(UpdateError):
        case.publisher.run()
    assert case.host.running and case.host.loaded == case.previous
    assert not case.config.maintenance_file.exists()


@pytest.mark.parametrize(
    "hour,minute,expected", [(4, 30, True), (5, 30, True), (6, 0, False), (12, 0, False)]
)
def test_scheduled_window_is_shanghai_and_never_catches_up_daytime(
    case, monkeypatch, hour, minute, expected
):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert str(tz) == "Asia/Shanghai"
            return cls(2026, 11, 12, hour, minute, tzinfo=tz)

    monkeypatch.setattr(nightly, "datetime", Clock)
    assert case.publisher._window(True) is expected
    if not expected:
        assert case.publisher.run(scheduled=True)["status"] == "outside_window"
        assert case.host.calls == []


def test_concurrent_worker_is_rejected(case):
    case.config.state_directory.mkdir()
    with publisher_lock(case.config.state_directory):
        with pytest.raises(UpdateError) as error:
            case.publisher.run()
    assert error.value.code == "WORKER_BUSY" and case.host.calls == []


def test_changed_input_rejected_before_stopping(case):
    (case.prepared / "graph-plan.json").write_text("changed")
    with pytest.raises(UpdateError) as error:
        case.publisher.run()
    assert error.value.code == "NIGHTLY_INPUT_CHANGED" and case.host.calls == []


def test_existing_manual_maintenance_is_preserved(case):
    case.config.maintenance_file.write_text("manual")
    with pytest.raises(UpdateError) as error:
        case.publisher.run()
    assert error.value.code == "NIGHTLY_ALREADY_MAINTAINED"
    assert case.config.maintenance_file.read_text() == "manual" and case.host.calls == []


def test_changed_instance_with_same_rows_still_requires_publication(case):
    metadata = json.loads((case.previous / "prepared.json").read_text())
    metadata["sources"][0]["host"] = "new-production.example.test"
    path = case.previous.parent / "migrated"
    path.mkdir()
    for name in PREPARED_FILES:
        shutil.copyfile(case.previous / name, path / name)
    save_json(path / "prepared.json", metadata)
    assert case.publisher.plan(path)["status"] == "update_available"


@pytest.mark.parametrize(
    "value",
    ["http://example.test", "https://127.0.0.1", "http://user@127.0.0.1", "http://127.0.0.1/path"],
)
def test_nonlocal_health_endpoint_rejected(case, value):
    data = case.config.model_dump()
    data["api_base_url"] = value
    with pytest.raises(ValidationError):
        NightlyConfig.model_validate(data)


def test_recovery_rejects_different_critical_configuration(case):
    case.host.crash = "build"
    with pytest.raises(KeyboardInterrupt):
        case.publisher.run()
    changed = case.config.model_copy(update={"query_service": "other.service"})
    with pytest.raises(UpdateError) as error:
        NightlyPublisher(changed, case.host).recover()
    assert error.value.code == "NIGHTLY_CONFIG_CHANGED"


def next_input(case, version, month):
    metadata = json.loads((case.prepared / "prepared.json").read_text())
    metadata.update(version=version, reference_month=month)
    with sqlite3.connect(case.prepared / "source.sqlite") as connection:
        connection.execute("UPDATE demo_dataset SET version=?,reference_month=?", (version, month))
    metadata["files"]["source.sqlite"] = checksum(case.prepared / "source.sqlite")
    save_json(case.prepared / "prepared.json", metadata)


def test_retention_removes_only_older_managed_releases(case):
    first = case.publisher.run()
    next_input(case, "nightly-third", 202701)
    second = case.publisher.run()
    next_input(case, "nightly-fourth", 202702)
    third = case.publisher.run()
    assert third["cleanup"] == {"status": "cleaned", "removed": 1}
    assert not Path(first["release"]).exists()
    assert Path(second["release"]).exists() and Path(third["release"]).exists()
    assert case.previous.exists()
    assert len(case.host.removed) == 1
    assert case.host.removed[0][0].startswith("relationship_lab_sync_")
    assert case.publisher.prune() == {"status": "cleaned", "removed": 0}


def test_cleanup_failure_keeps_new_publication_available_and_can_retry(case, monkeypatch):
    first = case.publisher.run()
    next_input(case, "nightly-third", 202701)
    case.publisher.run()
    next_input(case, "nightly-fourth", 202702)
    original = case.host.remove_graph

    def unavailable(*args):
        raise UpdateError("GRAPH_UNAVAILABLE", "cleanup")

    monkeypatch.setattr(case.host, "remove_graph", unavailable)
    result = case.publisher.run()
    assert result["status"] == "published" and result["cleanup"]["status"] == "pending"
    assert Path(first["release"]).exists() and not case.config.maintenance_file.exists()
    assert case.host.running
    monkeypatch.setattr(case.host, "remove_graph", original)
    assert case.publisher.prune()["removed"] == 1


def test_retention_rejects_resource_alias_to_active_graph(case):
    first = case.publisher.run()
    first_directory = Path(first["release"])
    next_input(case, "nightly-third", 202701)
    second = case.publisher.run()
    second_directory = Path(second["release"])
    # 模拟损坏的历史记录指向当前图，清理必须保留它所引用的运行资源。
    manifest = json.loads((first_directory / "manifest.json").read_text())
    active = json.loads((second_directory / "manifest.json").read_text())
    manifest["graph"]["space"] = active["graph"]["space"]
    save_json(first_directory / "manifest.json", manifest)
    save_json(first_directory / "graph/build-resource.json", {"space": active["graph"]["space"]})
    next_input(case, "nightly-fourth", 202702)
    result = case.publisher.run()
    assert result["cleanup"]["code"] == "NIGHTLY_CLEANUP_PROTECTED"
    assert case.host.removed == [] and first_directory.exists()


def test_candidate_ready_marker_incomplete_rolls_back(case):
    def change_manifest():
        operation = case.publisher.status()
        path = Path(operation["candidate"]) / "manifest.json"
        data = json.loads(path.read_text())
        data["validation"]["all_graph_rows_verified"] = False
        save_json(path, data)

    case.host.after_build = change_manifest
    with pytest.raises(UpdateError):
        case.publisher.run()
    assert case.host.running and case.host.loaded == case.previous
    assert not case.config.maintenance_file.exists()


def test_late_window_skips_before_service_changes(case, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 12, 5, 59, tzinfo=tz)

    monkeypatch.setattr(nightly, "datetime", Clock)
    assert case.publisher.run(scheduled=True)["status"] == "outside_window"
    assert case.host.calls == []


def test_environment_supports_quoted_paths_with_spaces(case):
    copied = case.previous.parent / "previous with spaces"
    shutil.copytree(case.previous, copied)
    case.config.environment_file.write_text(f'{ENV_KEY}="{copied}"\n')
    assert case.publisher.plan()["previous_release"] == str(copied)


def test_config_rejects_window_without_recovery_budget(case):
    values = case.config.model_dump()
    values["maintenance_timeout_seconds"] = 60
    with pytest.raises(ValidationError):
        NightlyConfig.model_validate(values)
