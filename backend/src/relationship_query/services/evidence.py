from collections.abc import Callable
from hashlib import sha256

from relationship_query.contracts import Evidence, FactView, RelationScope
from relationship_query.domain.models import RelationType
from relationship_query.domain.rules import RELATION_LABELS, month_count, overlap
from relationship_query.runtime.diagnostics import traced

SAME_SCHOOL_MAJOR_EXPLANATION = "双方已有同校关系，并关联同一标准专业。"


@traced("build_evidence")
def build_evidence(
    reference: list[FactView],
    candidate: list[FactView],
    reference_month: int,
    kind: RelationType | None = None,
    filters: RelationScope | None = None,
    check_pair: Callable[[], None] | None = None,
    evidence_limit: int | None = None,
) -> list[Evidence]:
    if filters and filters.require_same_school:
        schools = {v.entity.id for v in reference if v.fact.type == "education"}
        if not any(v.fact.type == "education" and v.entity.id in schools for v in candidate):
            return []
    result = []
    for a in reference:
        for b in candidate:
            if check_pair:
                check_pair()
            if a.fact.type != b.fact.type or a.entity.id != b.entity.id:
                continue
            evidence = _pair_evidence(a, b, reference_month)
            if (
                kind is None
                or evidence.relation_type == kind
                or (kind == "same_company" and evidence.relation_type == "same_company_overlap")
            ):
                scoped = scope_evidence(evidence, filters)
                if scoped is not None:
                    if filters and filters.require_same_school:
                        scoped = scoped.model_copy(
                            update={"explanation": SAME_SCHOOL_MAJOR_EXPLANATION}
                        )
                    result.append(scoped)
                    if evidence_limit is not None and len(result) >= evidence_limit:
                        return sort_evidence(result)
    return sort_evidence(result)


def sort_evidence(result: list[Evidence]) -> list[Evidence]:
    priority = {"same_company_overlap": 0, "same_company": 1, "same_school": 2, "same_major": 3}
    return sorted(result, key=lambda ev: (priority[ev.relation_type], ev.entity.id, ev.id))


def scope_evidence(evidence: Evidence, filters: RelationScope | None) -> Evidence | None:
    if filters is None:
        return evidence
    if (
        filters.relation_organization_ids
        and evidence.entity.id not in filters.relation_organization_ids
    ):
        return None
    if not any(
        v is not None
        for v in (
            filters.relation_start_month,
            filters.relation_end_month,
            filters.min_overlap_months,
        )
    ):
        return evidence
    if evidence.overlap_start is None or evidence.overlap_end is None:
        return None
    start = max(evidence.overlap_start, filters.relation_start_month or evidence.overlap_start)
    end = min(evidence.overlap_end, filters.relation_end_month or evidence.overlap_end)
    if start > end or month_count(start, end) < (filters.min_overlap_months or 1):
        return None
    months = month_count(start, end)
    return evidence.model_copy(
        update={
            "overlap_start": start,
            "overlap_end": end,
            "overlap_months": months,
            "explanation": (
                f"双方在所选时间范围内共同任职 {months} 个月，按单条经历对计算；"
                "共同经历不证明实际认识。"
            ),
        }
    )


def _pair_evidence(a: FactView, b: FactView, reference_month: int) -> Evidence:
    window = overlap(a.fact, b.fact, reference_month) if a.fact.type == "employment" else None
    kind: RelationType = (
        "same_major"
        if a.fact.type == "major"
        else (
            "same_school"
            if a.fact.type == "education"
            else ("same_company_overlap" if window else "same_company")
        )
    )
    return format_evidence(a, b, kind, window)


def format_evidence(
    a: FactView,
    b: FactView,
    kind: RelationType,
    window: tuple[int, int, int] | None,
    *,
    scoped: bool = False,
    require_same_school: bool = False,
) -> Evidence:
    """只装配已经确定的关系类型与窗口，不搜索或重新计算关系。"""
    explanation = {
        "same_major": "双方教育经历关联同一标准专业；不据此推断同校、同期或实际认识。",
        "same_school": "双方教育经历关联同一标准学校；不据此推断同期或实际认识。",
        "same_company": "双方曾任职同一标准公司；任职时间不重叠或时间信息不足。",
        "same_company_overlap": (
            f"双方任职区间重叠 {window[2] if window else 0} 个月；共同经历不证明实际认识。"
        ),
    }[kind]
    if kind == "same_major" and require_same_school:
        explanation = SAME_SCHOOL_MAJOR_EXPLANATION
    if scoped and window:
        explanation = (
            f"双方在所选时间范围内共同任职 {window[2]} 个月，按单条经历对计算；"
            "共同经历不证明实际认识。"
        )
    evidence_id = sha256(f"{a.fact.id}|{b.fact.id}|{kind}".encode()).hexdigest()[:24]
    return Evidence(
        id=f"ev:{evidence_id}",
        relation_type=kind,
        label=RELATION_LABELS[kind],
        entity=a.entity,
        reference=a,
        candidate=b,
        overlap_start=window[0] if window else None,
        overlap_end=window[1] if window else None,
        overlap_months=window[2] if window else None,
        explanation=explanation,
    )
