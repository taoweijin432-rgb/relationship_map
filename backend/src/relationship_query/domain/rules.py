from relationship_query.domain.models import Fact

RELATION_LABELS = {
    "same_company": "曾任职同一公司",
    "same_company_overlap": "同公司同期",
    "same_school": "同校",
    "same_major": "同专业",
}


def effective_end(fact: Fact, reference_month: int) -> int | None:
    return reference_month if fact.is_current else fact.end_month


def month_count(start: int, end: int) -> int:
    return (end // 100 - start // 100) * 12 + end % 100 - start % 100 + 1


def overlap(a: Fact, b: Fact, reference_month: int) -> tuple[int, int, int] | None:
    end_a, end_b = effective_end(a, reference_month), effective_end(b, reference_month)
    if a.start_month is None or b.start_month is None or end_a is None or end_b is None:
        return None
    start, end = max(a.start_month, b.start_month), min(end_a, end_b)
    if start > end:
        return None
    return start, end, month_count(start, end)
