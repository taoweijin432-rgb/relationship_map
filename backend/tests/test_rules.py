import pytest
from pydantic import ValidationError

from relationship_query.domain.models import Fact
from relationship_query.domain.rules import overlap


def fact(start: int | None, end: int | None, current: bool = False) -> Fact:
    return Fact(
        id="f:test",
        person_id="p:test",
        type="employment",
        entity_id="org:0",
        start_month=start,
        end_month=end,
        is_current=current,
        source_system="expert",
        source_record_id="test",
    )


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (fact(202312, 202401), fact(202311, 202402), (202312, 202401, 2)),
        (fact(202401, 202401), fact(202401, 202402), (202401, 202401, 1)),
        (fact(202401, 202412), fact(202501, 202512), None),
        (fact(None, None), fact(202401, 202412), None),
        (fact(202401, None, True), fact(202501, None, True), (202501, 202611, 23)),
        (fact(202701, None, True), fact(202501, None, True), None),
    ],
)
def test_month_intersections(a: Fact, b: Fact, expected: tuple[int, int, int] | None) -> None:
    assert overlap(a, b, 202611) == expected


def test_invalid_fact_intervals() -> None:
    with pytest.raises(ValidationError):
        fact(202501, 202401)
    with pytest.raises(ValidationError):
        fact(202613, None)
