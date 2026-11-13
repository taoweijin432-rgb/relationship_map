"""模拟上游修正指令应用于内存副本，发布前验证完整槽位和图差异。"""

import copy
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from relationship_query.domain.models import DomainModel
from relationship_query.infrastructure.projection_source_trial import projection_records
from relationship_query.infrastructure.source_read_model import SOURCE_NAMES, source_digest

MUTABLE_FIELDS = {
    "deleted_at",
    "company_name",
    "school_name",
    "canonical_name",
    "expert_id",
    "resume_id",
    "source_person_id",
    "entity_id",
}


class RowCorrection(DomainModel):
    table: str
    id: int = Field(gt=0, strict=True)
    expected: dict[str, Any] = Field(min_length=1)
    values: dict[str, Any] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @field_validator("table")
    @classmethod
    def known_table(cls, value: str) -> str:
        if value not in SOURCE_NAMES:
            raise ValueError("修正仅允许实验原表／三表，不允许任意表")
        return value

    @model_validator(mode="after")
    def safe_fields(self) -> "RowCorrection":
        if set(self.values) - MUTABLE_FIELDS or set(self.expected) - (MUTABLE_FIELDS | {"id"}):
            raise ValueError("不能修改主键／来源槽位键／类型或未知字段")
        return self


class CorrectionPlan(DomainModel):
    data_mode: Literal["mock"] = "mock"
    base_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    at: datetime
    corrections: list[RowCorrection] = Field(min_length=1, max_length=100)

    @field_validator("at")
    @classmethod
    def utc_naive(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _value(field: str, value: Any) -> Any:
    if field == "deleted_at":
        if value is None:
            return None
        result = datetime.fromisoformat(value)
        return result.astimezone(timezone.utc).replace(tzinfo=None) if result.tzinfo else result
    if field.endswith("_id") and (type(value) is not int or value < 1):
        raise ValueError("修正的引用标识必须为正整数")
    if field.endswith("_name") and (not isinstance(value, str) or not value.strip()):
        raise ValueError("修正名称不能为空")
    return value


def corrected_snapshot(data: dict[str, list[dict]], plan: CorrectionPlan) -> dict[str, list[dict]]:
    if source_digest(data) != plan.base_digest:
        raise ValueError("CORRECTION_BASE_MISMATCH：修正指令不是针对当前冻结版本")
    projection_records(data)
    result = copy.deepcopy(data)
    touched: set[tuple[str, int]] = set()
    for patch in plan.corrections:
        key = patch.table, patch.id
        if key in touched:
            raise ValueError(f"DUPLICATE_CORRECTION {key}")
        touched.add(key)
        matches = [r for r in result[patch.table] if r["id"] == patch.id]
        if len(matches) != 1:
            raise ValueError(f"CORRECTION_ROW_MISSING {key}")
        row = matches[0]
        if not set(patch.values).issubset(row) or any(
            k not in row or source_digest(row[k]) != source_digest(v)
            for k, v in patch.expected.items()
        ):
            raise ValueError(f"CORRECTION_PRECONDITION {key}")
        row.update({k: _value(k, v) for k, v in patch.values.items()})
        row["updated_at"] = plan.at
    projection_records(result)
    if source_digest(result) == plan.base_digest:
        raise ValueError("修正没有改变快照")
    return result


def projection_difference(before: dict, after: dict) -> dict:
    before_nodes, before_edges = projection_records(before)
    after_nodes, after_edges = projection_records(after)

    def key(edge: dict) -> tuple:
        return edge["source"], edge["target"], edge["type"], edge["rank"]

    old, new = {key(e): e for e in before_edges}, {key(e): e for e in after_edges}
    return {
        "old_node_count": len(before_nodes),
        "new_node_count": len(after_nodes),
        "old_edge_count": len(old),
        "new_edge_count": len(new),
        "removed_edges": [old[k] for k in sorted(old.keys() - new.keys())],
        "added_edges": [new[k] for k in sorted(new.keys() - old.keys())],
        "changed_properties": [k for k in sorted(old.keys() & new.keys()) if old[k] != new[k]],
        "note": "差异只用于完整新空间验收；不在已发布空间执行增量删除",
    }
