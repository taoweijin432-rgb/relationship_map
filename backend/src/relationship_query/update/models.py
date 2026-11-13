"""更新边界协议；采集器只能提交完整事务和明确的快照截止点。"""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Row = dict[str, JsonValue]


class UpdateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class UpdateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)


def encode(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Cursor(UpdateModel):
    """position由采集适配器解释，核心仅验证连续衔接，不按时间戳推断顺序。"""

    source: str = Field(min_length=1, max_length=128)
    position: Row


class RowChange(UpdateModel):
    event_id: str = Field(min_length=1, max_length=255)
    table: str = Field(min_length=1, max_length=255)
    operation: Literal["insert", "update", "delete", "ddl"]
    before: Row | None = None
    after: Row | None = None

    @model_validator(mode="after")
    def check_images(self) -> "RowChange":
        required = {
            "insert": self.after is not None and self.before is None,
            "update": self.before is not None and self.after is not None,
            "delete": self.before is not None and self.after is None,
            "ddl": True,
        }
        if not required[self.operation]:
            raise ValueError("事务事件缺少完整的前后行镜像")
        return self


class SourceTransaction(UpdateModel):
    format_version: Literal[1] = 1
    generation: str = Field(min_length=1, max_length=128)
    transaction_id: str = Field(min_length=1, max_length=255)
    previous: Cursor
    cursor: Cursor
    event_count: int = Field(ge=0)
    events: list[RowChange]

    @model_validator(mode="after")
    def check_complete(self) -> "SourceTransaction":
        if self.event_count != len(self.events):
            raise ValueError("事务事件数量不完整")
        if self.previous.source != self.cursor.source or self.previous == self.cursor:
            raise ValueError("事务来源或截止点不合法")
        ids = [event.event_id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("事务内事件编号重复")
        return self


class SourceSnapshot(UpdateModel):
    format_version: Literal[1] = 1
    data_mode: Literal["mock"] = "mock"
    generation: str = Field(min_length=1, max_length=128)
    cursor: Cursor
    tables: dict[str, list[Row]]


class Projection(UpdateModel):
    model: Literal["numeric-relations-v1"] = "numeric-relations-v1"
    nodes: list[Row]
    facts: list[Row]


class GraphReceipt(UpdateModel):
    backend: Literal["nebula", "test-double"]
    space: str
    graph_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    node_count: int = Field(ge=0)
    fact_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
