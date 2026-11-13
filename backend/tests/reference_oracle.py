"""仅测试使用的朴素基准：原始字典、日历月份集合，无生产查询或关系函数依赖。"""

from datetime import date
from typing import Any

Record = dict[str, Any]
Proof = tuple[str, str, str, str, tuple[int, int, int] | None]


def _months(fact: Record, reference_month: int) -> set[int] | None:
    start = fact.get("start_month")
    end = reference_month if fact.get("is_current", False) else fact.get("end_month")
    if start is None or end is None:
        return None
    cursor, last = date(start // 100, start % 100, 1), date(end // 100, end % 100, 1)
    months = set()
    while cursor <= last:
        months.add(cursor.year * 100 + cursor.month)
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return months


def active_facts(data: Record, person_id: str) -> list[Record]:
    return [f for f in data["facts"] if f["person_id"] == person_id and f.get("active", True)]


def expected_proofs(data: Record, reference_id: str, candidate_id: str) -> list[Proof]:
    persons = {p["id"]: p for p in data["people"]}
    if reference_id == candidate_id or not all(
        persons[p].get("active", True) for p in (reference_id, candidate_id)
    ):
        return []
    proofs = []
    for a in active_facts(data, reference_id):
        for b in active_facts(data, candidate_id):
            if a["type"] != b["type"] or a["entity_id"] != b["entity_id"]:
                continue
            window = None
            kind = "same_school"
            if a["type"] == "employment":
                months_a, months_b = (
                    _months(a, data["reference_month"]),
                    _months(b, data["reference_month"]),
                )
                common = (
                    months_a & months_b if months_a is not None and months_b is not None else set()
                )
                if common:
                    window = (min(common), max(common), len(common))
                kind = "same_company_overlap" if common else "same_company"
            proofs.append((kind, a["entity_id"], a["id"], b["id"], window))
    return proofs


def select_proofs(proofs: list[Proof], relation_type: str | None) -> list[Proof]:
    if relation_type is None:
        return proofs
    allowed = (
        {"same_company", "same_company_overlap"}
        if relation_type == "same_company"
        else {relation_type}
    )
    return [proof for proof in proofs if proof[0] in allowed]


def scoped_proofs(
    data: Record, reference_id: str, candidate_id: str, filters: Record
) -> list[Proof]:
    result = []
    for kind, entity, left, right, window in select_proofs(
        expected_proofs(data, reference_id, candidate_id), filters.get("relation_type")
    ):
        if (
            filters.get("relation_organization_ids")
            and entity not in filters["relation_organization_ids"]
        ):
            continue
        if any(
            filters.get(key) is not None
            for key in ("relation_start_month", "relation_end_month", "min_overlap_months")
        ):
            if window is None:
                continue
            months = _months(
                {"start_month": window[0], "end_month": window[1]}, data["reference_month"]
            )
            common = {
                month
                for month in months or set()
                if month >= (filters.get("relation_start_month") or 190001)
                and month <= (filters.get("relation_end_month") or 210012)
            }
            if len(common) < (filters.get("min_overlap_months") or 1):
                continue
            window = (min(common), max(common), len(common))
        result.append((kind, entity, left, right, window))
    return result


def _employment_matches(fact: Record, filters: Record, reference_month: int) -> bool:
    organizations = _choices(filters, "organization")
    roles = _choices(filters, "role")
    if organizations and fact["entity_id"] not in organizations:
        return False
    if roles and fact.get("role_id") not in roles:
        return False
    end = reference_month if fact.get("is_current", False) else fact.get("end_month")
    if filters.get("start_month") and (end is None or end < filters["start_month"]):
        return False
    start = fact.get("start_month")
    if filters.get("end_month") and (start is None or start > filters["end_month"]):
        return False
    return True


def _choices(filters: Record, category: str) -> set[str]:
    values = set(filters.get(f"{category}_ids") or [])
    if filters.get(f"{category}_id"):
        values.add(filters[f"{category}_id"])
    return values


def expected_people(data: Record, filters: Record, reference_id: str | None = None) -> list[str]:
    result = []
    employment_filter = bool(
        _choices(filters, "organization")
        or _choices(filters, "role")
        or filters.get("start_month")
        or filters.get("end_month")
    )
    schools = _choices(filters, "school")
    for person in data["people"]:
        person_id = person["id"]
        if not person.get("active", True) or person_id == reference_id:
            continue
        if filters.get("source") and filters["source"] not in person["sources"]:
            continue
        facts = active_facts(data, person_id)
        if schools and not any(
            f["type"] == "education" and f["entity_id"] in schools for f in facts
        ):
            continue
        if employment_filter and not any(
            f["type"] == "employment" and _employment_matches(f, filters, data["reference_month"])
            for f in facts
        ):
            continue
        if reference_id and not scoped_proofs(data, reference_id, person_id, filters):
            continue
        result.append(person_id)
    return sorted(result)
