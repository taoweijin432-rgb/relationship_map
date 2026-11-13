"""本机不可变快照的停服激活／回退；单一原子指针，不是分布式发布。"""

import fcntl
import hashlib
import json
import os
import shlex
import socket
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from relationship_query.domain.models import DomainModel
from relationship_query.infrastructure.graph_model import read_reader
from relationship_query.infrastructure.projection_source_trial import (
    open_projection_engine,
    projection_records,
)
from relationship_query.infrastructure.source_api import (
    SourceGraphClient,
    SourceRepository,
    read_source_manifest,
    validate_source_mysql_url,
)
from relationship_query.infrastructure.source_graph_model import SourceManifest
from relationship_query.infrastructure.source_publication import verify_graph
from relationship_query.infrastructure.source_read_model import snapshot
from relationship_query.services.query import QueryError


def bundle_digest(directory: Path) -> str:
    names = ["manifest.json", "api.env", "reader-credentials.json"]
    definition = json.loads((directory / "manifest.json").read_text())
    if not isinstance(definition, dict):
        raise ValueError("发布清单必须为 JSON 对象")
    if definition.get("format_version") == 5:
        names.append("mysql-ca.pem")
    files = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in names}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class SourceBundle:
    directory: Path
    manifest: SourceManifest
    mysql_url: str = field(repr=False)
    digest: str


def read_bundle(directory: Path) -> SourceBundle:
    directory = directory.resolve()
    digest = bundle_digest(directory)
    config = directory / "api.env"
    if config.stat().st_mode & 0o077:
        raise ValueError("API 配置应为 600 权限")
    values = {}
    for line in config.read_text().splitlines():
        tokens = shlex.split(line)
        if len(tokens) != 2 or tokens[0] != "export" or "=" not in tokens[1]:
            raise ValueError("API 配置只允许两项 export，不执行 shell 内容")
        name, value = tokens[1].split("=", 1)
        if name in values:
            raise ValueError("API 配置键不能重复")
        values[name] = value
    if set(values) != {"RELATIONSHIP_SOURCE_API_MANIFEST", "RELATIONSHIP_SOURCE_API_MYSQL_URL"}:
        raise ValueError("API 配置包含未知字段或缺少来源")
    manifest_path = directory / "manifest.json"
    if Path(values["RELATIONSHIP_SOURCE_API_MANIFEST"]).resolve() != manifest_path:
        raise ValueError("API 配置不能跨目录引用另一清单")
    manifest = read_source_manifest(manifest_path)
    url = values["RELATIONSHIP_SOURCE_API_MYSQL_URL"]
    validate_source_mysql_url(url, manifest)
    read_reader(manifest_path)
    if bundle_digest(directory) != digest:
        raise ValueError("读取候选配置期间内容发生变化")
    return SourceBundle(directory, manifest, url, digest)


def verify_bundle(directory: Path) -> SourceBundle:
    bundle = read_bundle(directory)
    from relationship_query.infrastructure.uuid_source import UUIDManifest
    from relationship_query.infrastructure.uuid_verification import verify_bundle_graph

    if isinstance(bundle.manifest, UUIDManifest):
        verify_bundle_graph(directory)
        if bundle_digest(bundle.directory) != bundle.digest:
            raise ValueError("候选配置在校验期间变化，拒绝激活")
        return bundle
    engine = open_projection_engine(bundle.mysql_url)
    try:
        repository = SourceRepository(engine, bundle.manifest)
        with engine.connect() as connection:
            nodes, edges = projection_records(snapshot(connection, repository.source_schema))
        client = SourceGraphClient(bundle.manifest, read_reader(directory / "manifest.json"))
        verify_graph(client, nodes, edges)
        repository.verify_snapshot()
        if bundle_digest(bundle.directory) != bundle.digest:
            raise ValueError("候选配置在校验期间变化，拒绝激活")
        return bundle
    finally:
        engine.dispose()


class ReleaseRef(DomainModel):
    directory: str
    bundle_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    data_version: str
    projection_id: str


class ReleaseEvent(DomainModel):
    revision: int = Field(ge=1)
    action: Literal["activate", "rollback"]
    previous_version: str | None
    data_version: str
    at: str


class ReleaseState(DomainModel):
    format_version: Literal[1] = 1
    revision: int = Field(ge=1)
    active: ReleaseRef
    previous: ReleaseRef | None = None
    history: list[ReleaseEvent]


def read_state(store: Path) -> ReleaseState:
    return ReleaseState.model_validate_json((store / "active.json").read_text())


@dataclass(frozen=True)
class ReleasePin:
    store: Path
    revision: int
    reference: ReleaseRef
    bundle: SourceBundle

    def check(self) -> None:
        try:
            state = read_state(self.store)
            valid = state.revision == self.revision and state.active == self.reference
            valid = valid and bundle_digest(self.bundle.directory) == self.reference.bundle_digest
        except (OSError, ValueError):
            valid = False
        if not valid:
            raise QueryError("RELEASE_CHANGED", "激活批次或配置已变化，请停止服务后重新启动", 409)


def load_active(store: Path) -> ReleasePin:
    state = read_state(store)
    bundle = read_bundle(Path(state.active.directory))
    if (
        bundle.digest != state.active.bundle_digest
        or bundle.manifest.data_version != state.active.data_version
        or bundle.manifest.projection_id != state.active.projection_id
    ):
        raise ValueError("激活记录与不可变配置不一致，拒绝启动")
    pin = ReleasePin(store.resolve(), state.revision, state.active, bundle)
    pin.check()
    return pin


@contextmanager
def _store_lock(store: Path) -> Iterator[None]:
    store.mkdir(parents=True, exist_ok=True)
    fd = os.open(store / ".release.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("另一版本切换正在执行") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def _stopped_services() -> Iterator[None]:
    # 保持端口占用直至指针替换完成，避免校验期间另一个 dev 进程启动。
    with ExitStack() as stack:
        for port in (8000, 5173):
            listener = stack.enter_context(socket.socket())
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listener.bind(("127.0.0.1", port))
                listener.listen(1)
            except OSError:
                raise RuntimeError(f"无法独占端口 {port}，请先停止前后端服务再切换") from None
        yield


def _atomic_state(store: Path, state: ReleaseState) -> None:
    fd, name = tempfile.mkstemp(prefix=".active-", suffix=".tmp", dir=store)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(state.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, store / "active.json")
    finally:
        Path(name).unlink(missing_ok=True)


def activate(store: Path, release: Path | None = None, *, rollback: bool = False) -> ReleaseState:
    if rollback == (release is not None):
        raise ValueError("选择一个候选批次或 rollback，不得同时指定")
    with _store_lock(store), _stopped_services():
        current = read_state(store) if (store / "active.json").exists() else None
        target = _target_release(current, release, rollback)
        bundle = verify_bundle(target)
        ref = ReleaseRef(
            directory=str(bundle.directory),
            bundle_digest=bundle.digest,
            data_version=bundle.manifest.data_version,
            projection_id=bundle.manifest.projection_id,
        )
        if rollback and current and current.previous != ref:
            raise ValueError("回退配置已变化，不能作为原历史批次使用")
        if current and current.active == ref:
            return current
        revision = current.revision + 1 if current else 1
        event = ReleaseEvent(
            revision=revision,
            action="rollback" if rollback else "activate",
            previous_version=current.active.data_version if current else None,
            data_version=ref.data_version,
            at=datetime.now(timezone.utc).isoformat(),
        )
        state = ReleaseState(
            revision=revision,
            active=ref,
            previous=current.active if current else None,
            history=[*(current.history if current else []), event],
        )
        _atomic_state(store, state)
        return state


def _target_release(current: ReleaseState | None, release: Path | None, rollback: bool) -> Path:
    if rollback:
        if current is None or current.previous is None:
            raise ValueError("没有已保留的上一批次可回退")
        return Path(current.previous.directory)
    if release is None:
        raise ValueError("缺少候选批次")
    return release.resolve()
