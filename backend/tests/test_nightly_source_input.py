"""夜间源采集先于停服，失败保留原服务，输入纳入既有发布预算。"""

import json
import shutil

import pytest

from relationship_query.update.models import UpdateError
from relationship_query.update.nightly import NightlyPublisher
from relationship_query.update.source_config import legacy_source_config

from .test_nightly_release import case as case
from .test_nightly_release import real_release as real_release
from .test_nightly_release import save_json


def automatic(case, monkeypatch):
    config = legacy_source_config("source").model_dump()
    for endpoint in config["connections"].values():
        endpoint["password_env"] = "TEST_ONLY_SOURCE_PASSWORD"
    monkeypatch.setenv("TEST_ONLY_SOURCE_PASSWORD", "fictional-password")
    path = case.previous.parent / "sources.json"
    save_json(path, config)
    settings = case.config.model_copy(update={"source_config_file": path})

    def prepare(directory, source_file, month, insecure, timeout):
        case.host.calls.append("input")
        assert case.host.running
        assert not settings.maintenance_file.exists()
        assert timeout > 0
        shutil.copytree(case.prepared, directory / "prepared")
        metadata = json.loads((directory / "prepared/prepared.json").read_text())
        metadata["person_display"] = "mysql-live"
        save_json(directory / "prepared/prepared.json", metadata)

    case.host.prepare_input = prepare
    before = case.host.build

    def build(directory, log, timeout):
        before(directory, log, timeout)
        manifest = json.loads((directory / "manifest.json").read_text())
        manifest["person_display"] = "mysql-live"
        save_json(directory / "manifest.json", manifest)

    case.host.build = build
    return NightlyPublisher(settings, case.host)


def test_automatic_capture_precedes_maintenance_and_publishes(case, monkeypatch):
    publisher = automatic(case, monkeypatch)
    result = publisher.run()
    assert result["status"] == "published"
    assert case.host.calls.index("input") < case.host.calls.index("maintenance")
    assert publisher.plan()["status"] == "up_to_date"
    assert publisher._latest_input().is_dir()


def test_prepare_input_reads_sources_while_api_stays_running(case, monkeypatch):
    publisher = automatic(case, monkeypatch)
    result = publisher.prepare_input()
    assert result["status"] == "input_prepared"
    assert result["plan"]["status"] == "update_available"
    assert case.host.calls == ["input"] and case.host.running
    assert not publisher.config.maintenance_file.exists()


def test_capture_failure_preserves_running_service_and_current_input(case, monkeypatch):
    publisher = automatic(case, monkeypatch)

    def fail(*args):
        raise UpdateError("NIGHTLY_INPUT_FAILED", "fictional failure")

    case.host.prepare_input = fail
    with pytest.raises(UpdateError, match="fictional"):
        publisher.run()
    assert case.host.running and case.host.calls == []
    assert publisher.status() == {"status": "idle"}
    assert not case.config.maintenance_file.exists()
    assert case.config.environment_file.read_bytes() == case.original


def test_automatic_capture_requires_noninteractive_credentials(case, monkeypatch):
    publisher = automatic(case, monkeypatch)
    monkeypatch.delenv("TEST_ONLY_SOURCE_PASSWORD")
    with pytest.raises(UpdateError) as error:
        publisher.run()
    assert error.value.code == "NIGHTLY_SOURCE_CREDENTIALS"
    assert case.host.calls == []


def test_unchanged_capture_skips_build_and_bounds_input_history(case, monkeypatch):
    publisher = automatic(case, monkeypatch)
    assert publisher.run()["status"] == "published"
    for _ in range(3):
        assert publisher.run()["status"] == "up_to_date"
    assert case.host.calls.count("build") == 1
    assert len(list((case.config.state_directory / "inputs").iterdir())) == 2


def test_automatic_input_pointer_rejects_external_directory(case, monkeypatch):
    publisher = automatic(case, monkeypatch)
    publisher.config.state_directory.mkdir()
    save_json(publisher.config.state_directory / "input.json", {"prepared": "/tmp/foreign"})
    with pytest.raises(UpdateError) as error:
        publisher.plan()
    assert error.value.code == "NIGHTLY_INPUT_INVALID"


def test_failed_captures_preserve_selected_input_during_retention(case, monkeypatch):
    publisher = automatic(case, monkeypatch)
    assert publisher.run()["status"] == "published"
    selected = publisher._latest_input()

    def fail(*args):
        raise UpdateError("NIGHTLY_INPUT_FAILED", "fictional failure")

    case.host.prepare_input = fail
    for _ in range(3):
        with pytest.raises(UpdateError):
            publisher.run()
    assert selected.is_dir()
    assert publisher.plan()["status"] == "up_to_date"


def test_live_display_mode_alone_requires_a_publication(case):
    metadata = json.loads((case.previous / "prepared.json").read_text())
    for name in metadata["files"]:
        shutil.copyfile(case.previous / name, case.prepared / name)
    metadata["person_display"] = "mysql-live"
    save_json(case.prepared / "prepared.json", metadata)
    assert case.publisher.plan()["status"] == "update_available"
