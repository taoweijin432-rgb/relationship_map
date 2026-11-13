import os
import stat
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from relationship_query.infrastructure import nebula_lab as lab


def test_credentials_persist_privately_without_rotation(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    first = lab.load_credentials(path, create=True)
    original = path.read_bytes()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert first.password.get_secret_value() not in repr(first)
    assert lab.load_credentials(path, create=True) == first
    assert path.read_bytes() == original
    path.chmod(0o644)
    with pytest.raises(ValueError, match="600"):
        lab.load_credentials(path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("host", "remote.example"),
        ("port", 9669),
        ("username", "other"),
        ("password", "quote'injection"),
        ("password", "f" * 25),
    ],
)
def test_credentials_reject_other_targets(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        lab.LabCredentials.model_validate({"password": "f" * 24, field: value})


@pytest.mark.parametrize(
    "space",
    [
        "production",
        "relationship_lab_x`;DROP SPACE y",
        "relationship_lab_",
        "relationship_lab_" + "a" * 41,
    ],
)
def test_space_guard(space: str) -> None:
    with pytest.raises(ValueError):
        lab.require_space(space)


class Result:
    def __init__(self, code: int = 0, message: str = "") -> None:
        self.code, self.message = code, message

    def is_succeeded(self) -> bool:
        return self.code == 0

    def error_code(self) -> int:
        return self.code

    def error_msg(self) -> str:
        return self.message

    def as_primitive(self) -> list:
        return [{"ready": True}]


@pytest.mark.parametrize(
    "code,message",
    [
        (-4, "leader"),
        (-5, "space"),
        (-6, "tag"),
        (-7, "edge"),
        (-16, "part"),
        (-1005, "SpaceNotFound: lab"),
        (-1005, "Storage Error: Tag not found."),
        (-1005, "Storage Error: Edge not found."),
        (-1009, "SemanticError: No schema found for `person'"),
    ],
)
def test_retries_only_known_async_states(
    monkeypatch: pytest.MonkeyPatch, code: int, message: str
) -> None:
    results = iter([Result(code, message), Result()])

    class Session:
        def execute(self, _statement: str) -> Result:
            return next(results)

    monkeypatch.setattr(lab, "sleep", lambda _seconds: None)
    assert lab.query(Session(), "fictional statement", wait=True) == [{"ready": True}]


@pytest.mark.parametrize("code", [-1004, -1005, -1009, -1001])
def test_other_failures_do_not_retry_or_expose_statement(code: int) -> None:
    class Session:
        def execute(self, _statement: str) -> Result:
            return Result(code, "private SQL input must not be printed")

    with pytest.raises(lab.LabQueryError) as error:
        lab.query(Session(), "private SQL input", wait=True)
    assert error.value.code == code
    assert "private" not in str(error.value)


def test_wait_deadline_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([0, 61])
    monkeypatch.setattr(lab, "monotonic", lambda: next(times))

    class Session:
        def execute(self, _statement: str) -> Result:
            return Result(-5)

    with pytest.raises(lab.LabQueryError):
        lab.query(Session(), "USE fictional", wait=True)


def test_pool_cleanup_and_no_default_password_after_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = []

    class Session:
        def release(self) -> None:
            events.append("release")

    class Pool:
        def init(self, _addresses: list, _options: object) -> bool:
            return True

        def get_session(self, _username: str, _password: str) -> Session:
            return Session()

        def close(self) -> None:
            events.append("close")

    monkeypatch.setattr(lab, "ConnectionPool", Pool)
    config = lab.LabCredentials(password=SecretStr("f" * 24), bootstrapped=True)
    with pytest.raises(RuntimeError, match="business failure"):
        with lab.connect(config):
            raise RuntimeError("business failure")
    assert events == ["release", "close"]

    class AuthFailure(Pool):
        def get_session(self, _username: str, password: str) -> Session:
            assert password == config.password.get_secret_value()
            raise lab.AuthFailedException("invalid")

    monkeypatch.setattr(lab, "ConnectionPool", AuthFailure)
    with pytest.raises(lab.LabAuthenticationError):
        with lab.connect(config, bootstrap=True):
            pytest.fail("不应进入认证失败会话")
    assert events[-1] == "close"


@pytest.mark.skipif(
    os.environ.get("RELATIONSHIP_NEBULA_TEST") != "1", reason="显式启用独立 NebulaGraph 环境验收"
)
def test_live_environment_roundtrip_and_authentication() -> None:
    config = lab.load_credentials(lab.DEFAULT_CREDENTIALS)
    status = lab.check(lab.DEFAULT_CREDENTIALS)
    assert status["storage_hosts"][0]["Status"] == "ONLINE"
    report = lab.smoke(lab.DEFAULT_CREDENTIALS)
    try:
        assert lab.verify(lab.DEFAULT_CREDENTIALS, report)["snapshot_matches"]
        wrong = config.model_copy(update={"password": SecretStr("0" * 24)})
        with pytest.raises(lab.LabAuthenticationError):
            with lab.connect(wrong):
                pytest.fail("错误密码不能通过认证")
    finally:
        with lab.connect(config) as session:
            lab.query(session, f"DROP SPACE `{lab.require_space(report['space'])}`")
