"""服务器凭据文件的引用、转义和失败恢复，使用本地文件及连接替身。"""

import importlib.util
from pathlib import Path

import pytest

from relationship_query.update.source_config import legacy_source_config


@pytest.fixture
def setup_module():
    path = Path(__file__).resolve().parents[2] / "scripts/configure_server_mysql.py"
    spec = importlib.util.spec_from_file_location("mysql_config_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "password", ["abc/123+=", "a# $() `x` ' \" \\ 中文\t", " spaced password "]
)
def test_environment_file_roundtrip_and_private_mode(setup_module, tmp_path, password):
    values = {"MYSQL_PASSWORD": password, "OTHER": "x"}
    path = tmp_path / "mysql.env"
    setup_module.atomic_file(path, setup_module.environment_bytes(values))
    assert setup_module.read_environment(path) == values
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("value", ["a\nb", "a\rb", "a\x00b"])
def test_environment_rejects_multiline_values(setup_module, value):
    with pytest.raises(ValueError):
        setup_module.environment_bytes({"PASSWORD": value})


def test_shared_connection_prompts_once_and_binds_one_password(setup_module, monkeypatch):
    config = legacy_source_config("source")
    config = config.model_copy(update={"person_source": config.entity_source})
    calls = []
    monkeypatch.setattr(
        setup_module.getpass, "getpass", lambda prompt: calls.append(prompt) or "fake"
    )
    values = {}
    configured = setup_module.password_config(config, values, False)
    assert len(calls) == 1
    assert (
        configured.endpoint("entities").password_env == configured.endpoint("people").password_env
    )
    assert list(values.values()) == ["fake"]


def test_failed_configuration_write_restores_originals(setup_module, monkeypatch, tmp_path):
    first = tmp_path / "source.json"
    second = tmp_path / "mysql.env"
    first.write_bytes(b"original")
    actual = setup_module.atomic_file

    def fail(path, data):
        if path == second:
            raise OSError("fictional disk failure")
        actual(path, data)

    monkeypatch.setattr(setup_module, "atomic_file", fail)
    with pytest.raises(OSError):
        setup_module.write_configuration(tmp_path, {first: b"new", second: b"secret"})
    assert first.read_bytes() == b"original"
    assert not second.exists()
