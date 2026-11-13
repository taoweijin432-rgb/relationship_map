"""独立发布目录。当前API的历史发布格式与此显式区分。"""

import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field

from relationship_query.update.contract import SourceContract
from relationship_query.update.models import GraphReceipt, Row, UpdateError, UpdateModel, encode


class BuildManifest(UpdateModel):
    format: Literal["standalone-update-v1"] = "standalone-update-v1"
    data_mode: Literal["mock"] = "mock"
    state: Literal["planned", "verified"]
    batch_id: str
    token: int
    contract_digest: str
    generation: str
    from_seq: int
    to_seq: int
    reference_month: int
    version: str
    source_digest: str
    files: dict[str, str]
    graph: GraphReceipt | None = None


class ReleasePointer(UpdateModel):
    format: Literal["standalone-update-v1"] = "standalone-update-v1"
    revision: int = Field(ge=1)
    batch_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    token: int = Field(ge=1)
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def checksum(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as file:
        os.chmod(path, 0o600)
        file.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        file.flush()
        os.fsync(file.fileno())


@contextmanager
def publisher_lock(directory: Path) -> Iterator[None]:
    fd = os.open(directory / ".publisher.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateError("WORKER_BUSY", "另一个发布进程正在运行") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def artifact_directory(directory: Path, batch_id: str, token: int) -> Path:
    result = directory / "releases" / batch_id / str(token)
    if not result.resolve().is_relative_to(directory.resolve()):
        raise UpdateError("ARTIFACT_INTEGRITY", "发布目录超出独立状态范围")
    return result


def source_sqlite(path: Path, contract: SourceContract, rows: dict[str, list[Row]]) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE source_row(logical_table TEXT,row_key TEXT,payload TEXT,"
            "PRIMARY KEY(logical_table,row_key))"
        )
        for table, records in rows.items():
            connection.executemany(
                "INSERT INTO source_row VALUES (?,?,?)",
                [(table, contract.tables[table].row_key(row), encode(row)) for row in records],
            )


def load_active(
    directory: Path, contract: SourceContract
) -> tuple[ReleasePointer, BuildManifest] | None:
    path = directory / "active.json"
    if not path.exists():
        return None
    try:
        pointer = ReleasePointer.model_validate_json(path.read_text())
        target = artifact_directory(directory, pointer.batch_id, pointer.token)
        if checksum(target / "manifest.json") != pointer.manifest_digest:
            raise ValueError("manifest changed")
        manifest = BuildManifest.model_validate_json((target / "manifest.json").read_text())
        if (
            manifest.state != "verified"
            or manifest.graph is None
            or manifest.contract_digest != contract.fingerprint
            or (manifest.batch_id, manifest.token) != (pointer.batch_id, pointer.token)
        ):
            raise ValueError("release mismatch")
        required = {"source.sqlite", "source-snapshot.json", "graph-plan.json"}
        if manifest.graph.backend == "nebula":
            required.add("reader-credentials.json")
        # v0.30已发布清单没有资源日志，继续兼容这些不可变历史产物。
        allowed = required | {"build-resource.json"}
        if not required.issubset(manifest.files) or not set(manifest.files).issubset(allowed):
            raise ValueError("artifact list mismatch")
        for name, expected in manifest.files.items():
            if checksum(target / name) != expected:
                raise ValueError("artifact changed")
        return pointer, manifest
    except (OSError, ValueError):
        raise UpdateError("ARTIFACT_INTEGRITY", "激活配置或发布文件校验失败") from None


def replace_active(directory: Path, pointer: ReleasePointer) -> None:
    target = artifact_directory(directory, pointer.batch_id, pointer.token)
    # 先落盘候选文件及各层目录，再让持久激活指针引用它们。
    paths = [*target.iterdir(), target, target.parent, target.parent.parent, directory]
    for path in paths:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    fd, name = tempfile.mkstemp(prefix=".active-", dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as file:
            file.write(pointer.model_dump_json(indent=2))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, directory / "active.json")
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
