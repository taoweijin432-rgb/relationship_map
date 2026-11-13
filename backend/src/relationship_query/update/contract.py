"""物理表／列变化在此收口。复杂业务变更由显式版本的投影适配器处理。"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, model_validator

from relationship_query.update.models import Row, UpdateError, UpdateModel, digest, encode

AUTHORITATIVE_ADAPTERS = {"numeric-authoritative-v1", "numeric-authoritative-v2"}


class TableBinding(UpdateModel):
    physical: str = Field(min_length=1, max_length=255)
    columns: dict[str, str]
    key: list[str] = Field(default_factory=lambda: ["id"], min_length=1)
    integer_fields: list[str] = Field(default_factory=list)
    datetime_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_columns(self) -> "TableBinding":
        if not set(self.key).issubset(self.columns) or len(self.key) != len(set(self.key)):
            raise ValueError("主键必须映射到已配置字段且不可重复")
        if len(set(self.columns.values())) != len(self.columns):
            raise ValueError("一个来源字段只能绑定一个逻辑字段")
        if not set(self.integer_fields).issubset(self.columns):
            raise ValueError("整数类型字段必须已配置映射")
        if not set(self.datetime_fields).issubset(self.columns) or set(self.datetime_fields) & set(
            self.integer_fields
        ):
            raise ValueError("时间字段必须已配置映射且不能同时声明为整数")
        return self

    def normalize(self, row: Row) -> Row:
        if not set(self.columns.values()).issubset(row):
            raise UpdateError("SCHEMA_MISMATCH", f"来源表 {self.physical} 缺少配置字段")
        result = {logical: row[physical] for logical, physical in self.columns.items()}
        for field in self.integer_fields:
            value = result[field]
            if value is None:
                continue
            if type(value) is int:
                number = value
            elif isinstance(value, str) and value.isascii() and value.isdecimal():
                number = int(value)
            else:
                raise UpdateError("FIELD_TYPE_CHANGED", f"来源表 {self.physical} 整数字段类型不符")
            if not -(2**63) <= number < 2**63:
                raise UpdateError("FIELD_TYPE_CHANGED", "整数字段超出有符号64位范围")
            result[field] = number
        for field in self.datetime_fields:
            value = result[field]
            if value is None:
                continue
            try:
                if not isinstance(value, str):
                    raise ValueError("date format")
                parsed = datetime.fromisoformat(value)
            except ValueError:
                raise UpdateError("FIELD_TYPE_CHANGED", "时间字段需要ISO日期或明确NULL") from None
            parsed = (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed.astimezone(timezone.utc)
            )
            result[field] = parsed.isoformat(timespec="microseconds")
        return result

    def row_key(self, row: Row) -> str:
        values = [row[field] for field in self.key]
        if any(value is None or isinstance(value, (dict, list, bool, float)) for value in values):
            raise UpdateError("INVALID_KEY", "来源主键必须为非空整数或字符串")
        return encode(values)


class ExperienceBinding(UpdateModel):
    table: str
    source: str
    person_table: str
    source_table_value: str
    fields: dict[str, str]


class NamespaceBinding(UpdateModel):
    experience_table: str
    entity_type: str
    id_prefix: str = ""


class SourceContract(UpdateModel):
    format_version: Literal[1] = 1
    version: str = Field(min_length=1, max_length=128)
    adapter: str = "numeric-v1"
    tables: dict[str, TableBinding]
    people: dict[str, str]
    experiences: list[ExperienceBinding]
    namespaces: dict[str, NamespaceBinding]
    entity_statuses: dict[str, list[str]]
    inactive_entity_statuses: dict[str, list[str]] = Field(default_factory=dict)
    matched_statuses: list[str] = Field(default_factory=list)
    unmatched_statuses: list[str] = Field(default_factory=list)
    current_values: list[int] = Field(default_factory=lambda: [1])
    past_values: list[int] = Field(default_factory=lambda: [2])

    @model_validator(mode="after")
    def check_bindings(self) -> "SourceContract":
        physical = [binding.physical for binding in self.tables.values()]
        if len(physical) != len(set(physical)):
            raise ValueError("来源物理表绑定重复")
        if self.adapter not in {"numeric-v1", *AUTHORITATIVE_ADAPTERS} or set(self.people) != {
            "expert",
            "resume",
        }:
            raise ValueError("需要显式支持的适配器及专家／简历来源配置")
        if self.adapter == "numeric-v1" and not self.matched_statuses:
            raise ValueError("名称映射表模式需要已匹配状态配置")
        if self.adapter in AUTHORITATIVE_ADAPTERS and (
            self.namespaces
            or self.matched_statuses
            or self.unmatched_statuses
            or "name_mapping" in self.tables
        ):
            raise ValueError("权威事实映射模式不接收名称匹配表及其状态")
        if len(set(self.people.values())) != 2:
            raise ValueError("专家和简历须明确绑定各自人物表")
        if set(self.entity_statuses) != {"company", "school", "major"} or not all(
            self.entity_statuses.values()
        ):
            raise ValueError("三类实体可用状态必须显式配置")
        if set(self.current_values) & set(self.past_values):
            raise ValueError("在职与非在职状态配置冲突")
        if set(self.matched_statuses) & set(self.unmatched_statuses) or any(
            set(active) & set(self.inactive_entity_statuses.get(kind, []))
            for kind, active in self.entity_statuses.items()
        ):
            raise ValueError("有效与无效状态配置冲突")
        for experience in self.experiences:
            if (
                experience.table not in self.tables
                or self.people.get(experience.source) != experience.person_table
                or not experience.fields
                or not set(experience.fields).issubset({"worked_at", "studied_at", "studied_major"})
            ):
                raise ValueError("经历来源配置不完整")
        covered = {(entry.source, kind) for entry in self.experiences for kind in entry.fields}
        expected = {
            (source, kind)
            for source in self.people
            for kind in ("worked_at", "studied_at", "studied_major")
        }
        if covered != expected:
            raise ValueError("数字来源契约须明确覆盖专家和简历的三类事实")
        for namespace in self.namespaces.values():
            if namespace.experience_table not in {
                entry.table for entry in self.experiences
            } or namespace.entity_type not in {
                "company",
                "school",
                "major",
            }:
                raise ValueError("名称映射命名空间配置不完整")
        return self

    @property
    def fingerprint(self) -> str:
        return digest(self.model_dump(mode="json"))

    def logical_table(self, physical: str) -> str | None:
        return next(
            (name for name, table in self.tables.items() if table.physical == physical), None
        )

    def snapshot(self, tables: dict[str, list[Row]]) -> dict[str, list[Row]]:
        if set(tables) != {table.physical for table in self.tables.values()}:
            raise UpdateError("SCHEMA_MISMATCH", "全量输入必须覆盖配置的全部来源表")
        return {
            name: [binding.normalize(row) for row in tables[binding.physical]]
            for name, binding in self.tables.items()
        }
