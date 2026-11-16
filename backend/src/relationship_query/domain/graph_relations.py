"""图关系引擎输出的事实引用；SQL 负责按引用补充详情，不重新选路径。"""

from typing import Any

from pydantic import model_validator

from relationship_query.domain.models import DomainModel, Month, RelationType

PROOF_PAIR_BATCH = 16


class GraphProof(DomainModel):
    left_person: str
    right_person: str
    entity_id: str
    left_fact: str
    right_fact: str
    kind: RelationType
    start_month: Month | None
    end_month: Month | None
    months: int | None
    left_properties: dict[str, Any]
    right_properties: dict[str, Any]

    @model_validator(mode="after")
    def check_window(self) -> "GraphProof":
        values = (self.start_month, self.end_month, self.months)
        if self.kind == "same_company_overlap":
            if any(v is None for v in values) or (self.months or 0) < 1:
                raise ValueError("图同期证据缺少有效窗口")
            if (
                self.start_month is not None
                and self.end_month is not None
                and self.start_month > self.end_month
            ):
                raise ValueError("图同期窗口逆序")
        elif any(v is not None for v in values):
            raise ValueError("图非同期证据不应提供同期窗口")
        return self
