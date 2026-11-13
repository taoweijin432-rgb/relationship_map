"""三表原表集成清单与图证据协议，不接受旧实验清单冒充 API 配置。"""

from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator

from relationship_query.domain.models import DomainModel, Month
from relationship_query.infrastructure.mysql import LAB_DATABASE, SOURCE_DATABASE
from relationship_query.infrastructure.nebula_lab import require_space


class SourceManifest(DomainModel):
    format_version: Literal[2] = 2
    model: Literal["source-slots-v2"] = "source-slots-v2"
    data_mode: Literal["mock"] = "mock"
    reference_month: Month
    status: Literal["ready"] = "ready"
    space: str
    projection_id: str
    data_version: str
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    counts: dict[str, int]
    source_database: str
    block_size: Literal[128] = 128

    @field_validator("space")
    @classmethod
    def check_space(cls, value: str) -> str:
        return require_space(value)

    @field_validator("source_database")
    @classmethod
    def check_database(cls, value: str, info: ValidationInfo) -> str:
        pattern = SOURCE_DATABASE if info.data.get("format_version") == 5 else LAB_DATABASE
        if not pattern.fullmatch(value):
            raise ValueError("原表集成仅接受独立本机实验库")
        return value


class SlotProperties(DomainModel):
    fact_id: str
    kind: Literal["employment", "education"]
    active: Literal[True]
    start_date: Month | None
    end_date: Month | None
    is_current: bool
    role_id: int | None = Field(ge=1, le=2**63 - 1)
    source_system: Literal["expert", "resume"]
    source_record_id: str
    source_table: str
    source_field_id: int = Field(ge=1, le=2**63 - 1)
    source_field: str


def normalize_slot_proof(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for side in ("left", "right"):
        properties = SlotProperties.model_validate(result[side + "_properties"])
        rank = result.pop(side + "_rank")
        prefix = "experts" if properties.source_system == "expert" else "resume"
        suffix = "work_experience" if properties.kind == "employment" else "education_experience"
        field = "company_name" if properties.kind == "employment" else "school_name"
        if (
            type(rank) is not int
            or not 0 < rank <= 2**63 - 1
            or properties.fact_id != f"slot:{rank}"
            or properties.fact_id != result[side + "_fact"]
            or properties.source_table != f"{prefix}_{suffix}"
            or properties.source_field != field
            or properties.source_record_id
            != f"{properties.source_table}:{properties.source_field_id}"
            or not result[side + "_person"].startswith(f"p:{properties.source_system}:")
        ):
            raise ValueError("图边槽位 Rank 或原表定位不一致")
        result[side + "_properties"] = dict(
            fact_id=properties.fact_id,
            kind=properties.kind,
            active=properties.active,
            start_month=properties.start_date,
            end_month=properties.end_date,
            is_current=properties.is_current,
            role_id=str(properties.role_id) if properties.role_id is not None else None,
            source_system=properties.source_system,
            source_record_id=properties.source_record_id,
        )
    return result
