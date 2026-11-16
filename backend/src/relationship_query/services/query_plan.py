"""可复用的ID选择结果与仅属于当前请求的装配产物。"""

from dataclasses import dataclass

from relationship_query.contracts import Evidence, FactView, SearchResponse


@dataclass(frozen=True)
class PersonPagePlan:
    data_version: str
    reference_month: int
    reference_id: str | None
    fingerprint: str
    ids: tuple[str, ...]
    has_more: bool
    next_cursor: str | None


@dataclass
class DirectPage:
    # 包含实时人物，只可在本次请求复用，不能放入跨请求关系缓存。
    response: SearchResponse
    facts: list[FactView]
    graph_facts: list[FactView]
    evidence: dict[tuple[str, str], list[Evidence]]
