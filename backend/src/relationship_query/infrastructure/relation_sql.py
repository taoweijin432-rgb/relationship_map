from typing import Any

from sqlalchemy import and_, case, or_, select
from sqlalchemy.sql.elements import ColumnElement

from relationship_query.contracts import RelationScope
from relationship_query.infrastructure.read_model import facts


def neighborhood_probe(reference_id: str, scope: RelationScope, fact_table: Any = facts) -> Any:
    """只探测 513 条关联事实，不做全量计数；阈值需按正式环境重评。"""
    anchor = fact_table.alias("degree_anchor")
    conditions = [anchor.c.person_id == reference_id, anchor.c.active.is_(True)]
    if scope.relation_type in ("same_company", "same_company_overlap"):
        conditions.append(anchor.c.type == "employment")
    elif scope.relation_type == "same_school":
        conditions.append(anchor.c.type == "education")
    if scope.relation_organization_ids:
        conditions.append(anchor.c.entity_id.in_(scope.relation_organization_ids))
    return (
        select(fact_table.c.person_id)
        .where(
            fact_table.c.active.is_(True),
            fact_table.c.entity_id.in_(select(anchor.c.entity_id).where(*conditions)),
        )
        .limit(513)
    )


def effective_end(table: Any, reference_month: int) -> Any:
    return case((table.c.is_current.is_(True), reference_month), else_=table.c.end_month)


def relation_pair_condition(
    a: Any, b: Any, scope: RelationScope, reference_month: int
) -> ColumnElement[bool]:
    common = [
        a.c.active.is_(True),
        b.c.active.is_(True),
        a.c.entity_id == b.c.entity_id,
        a.c.type == b.c.type,
    ]
    if scope.relation_organization_ids:
        common.append(a.c.entity_id.in_(scope.relation_organization_ids))
    company, school = a.c.type == "employment", a.c.type == "education"
    if scope.relation_type == "same_company_overlap":
        relation = and_(company, _overlap_condition(a, b, scope, reference_month))
    elif scope.relation_type == "same_company":
        relation = company
    elif scope.relation_type == "same_school":
        relation = school
    else:
        relation = or_(company, school)
    return and_(*common, relation)


def _overlap_condition(
    a: Any, b: Any, scope: RelationScope, reference_month: int
) -> ColumnElement[bool]:
    start = case((a.c.start_month >= b.c.start_month, a.c.start_month), else_=b.c.start_month)
    end_a, end_b = effective_end(a, reference_month), effective_end(b, reference_month)
    end = case((end_a <= end_b, end_a), else_=end_b)
    if scope.relation_start_month is not None:
        start = case((start >= scope.relation_start_month, start), else_=scope.relation_start_month)
    if scope.relation_end_month is not None:
        end = case((end <= scope.relation_end_month, end), else_=scope.relation_end_month)
    months = (end // 100 - start // 100) * 12 + end % 100 - start % 100 + 1
    return and_(
        a.c.start_month.is_not(None),
        b.c.start_month.is_not(None),
        end_a.is_not(None),
        end_b.is_not(None),
        start <= end,
        months >= (scope.min_overlap_months or 1),
    )
