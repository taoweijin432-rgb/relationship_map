"""可复用的ID选择结果与仅属于当前请求的装配产物。"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any

from relationship_query.contracts import Evidence, FactView, SearchResponse
from relationship_query.domain.path_budget import PathBudget
from relationship_query.runtime.relation_cache import RelationCache

PLAN_CACHE_FORMAT = "http-id-plan-v3"


@dataclass(frozen=True)
class PersonPagePlan:
    data_version: str
    reference_month: int
    reference_id: str | None
    fingerprint: str
    ids: tuple[str, ...]
    has_more: bool
    next_cursor: str | None
    query_key: str = ""
    chains: tuple[tuple[str, tuple[str, ...]], ...] | None = None
    probe_id: str | None = None

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> "PersonPagePlan":
        return cls(
            **{
                **value,
                "ids": tuple(value["ids"]),
                "chains": tuple((key, tuple(path)) for key, path in value["chains"])
                if value["chains"] is not None
                else None,
            }
        )


_prepared: ContextVar[PersonPagePlan | None] = ContextVar("prepared_id_plan", default=None)


def supplied_plan(key: str) -> PersonPagePlan | None:
    plan = _prepared.get()
    if plan is not None and plan.query_key != key:
        # 计划不匹配时不能在轻量装配中偷偷回到重计算路径。
        raise RuntimeError("Prepared ID plan does not match the query")
    return plan


def cached_plan(cache: RelationCache | None, key: str, budget: PathBudget) -> PersonPagePlan | None:
    payload = cache.lookup([PLAN_CACHE_FORMAT, key], budget) if cache is not None else None
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise RuntimeError("Invalid cached ID plan")
    plan = PersonPagePlan.from_payload(payload)
    if plan.query_key != key:
        raise RuntimeError("Cached ID plan scope mismatch")
    return plan


def store_plan(cache: RelationCache | None, plan: PersonPagePlan, budget: PathBudget) -> None:
    if cache is not None:
        cache.store([PLAN_CACHE_FORMAT, plan.query_key], plan.payload(), budget)


@contextmanager
def prepared_plan(plan: PersonPagePlan) -> Iterator[None]:
    token = _prepared.set(plan)
    try:
        yield
    finally:
        _prepared.reset(token)


@dataclass
class DirectPage:
    # 包含实时人物，只可在本次请求复用，不能放入跨请求关系缓存。
    response: SearchResponse
    facts: list[FactView]
    graph_facts: list[FactView]
    evidence: dict[tuple[str, str], list[Evidence]]
