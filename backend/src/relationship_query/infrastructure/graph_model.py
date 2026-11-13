"""不可变模拟图投影契约；辅助成员块不是全库人物两两关系。"""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from relationship_query.infrastructure.nebula_lab import require_space

BLOCK_SIZE: Literal[128] = 128
FORMAT_VERSION: Literal[1] = 1


def literal(value: object) -> str:
    return "NULL" if value is None else json.dumps(value, ensure_ascii=False)


def vid(kind: Literal["p", "e", "b"], identity: str, index: int | None = None) -> str:
    value = f"{kind}|{identity}" + (f"|{index}" if index is not None else "")
    if len(value.encode()) > 128:
        raise ValueError("模拟图 VID 超过 128 字节，请重新评估映射，不能截断标识")
    return value


def ids_digest(ids: list[str]) -> str:
    return hashlib.sha256(json.dumps(ids, ensure_ascii=False).encode()).hexdigest()


class ProjectionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    format_version: Literal[1] = FORMAT_VERSION
    block_size: Literal[128] = BLOCK_SIZE
    status: Literal["ready"] = "ready"
    space: str
    projection_id: str
    data_version: str
    reference_month: int
    source_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    counts: dict[str, int]

    @field_validator("space")
    @classmethod
    def check_space(cls, value: str) -> str:
        return require_space(value)


class ReaderCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: Literal[19669] = 19669
    username: Annotated[str, Field(pattern=r"^rq_[0-9a-f]{12}$")]
    password: SecretStr

    @field_validator("password")
    @classmethod
    def check_password(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) != 24 or any(
            c not in "0123456789abcdef" for c in value.get_secret_value()
        ):
            raise ValueError("图查询凭据不是本工具生成的值")
        return value


def read_manifest(path: Path) -> ProjectionManifest:
    return ProjectionManifest.model_validate_json(path.read_text())


def read_reader(path: Path) -> ReaderCredentials:
    file = path.parent / "reader-credentials.json"
    if file.stat().st_mode & 0o077:
        raise ValueError("图查询凭据应为 600 权限")
    return ReaderCredentials.model_validate_json(file.read_text())
