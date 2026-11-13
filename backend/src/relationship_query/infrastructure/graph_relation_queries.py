"""图内关系谓词；SQL 只接收图返回的事实 ID，不参与候选与路径过滤。"""

from dataclasses import dataclass

from relationship_query.contracts import PathRequest, RelationScope
from relationship_query.infrastructure.graph_model import literal, vid


@dataclass(frozen=True)
class GraphQueryModel:
    source_slots: bool = False

    def person_vid(self, identity: str) -> str:
        return identity if self.source_slots else vid("p", identity)

    def edge_pattern(self, scope: RelationScope) -> str:
        if not self.source_slots:
            return "experience"
        if scope.relation_type == "same_school":
            return "studied_at"
        if scope.relation_type in {"same_company", "same_company_overlap"}:
            return "worked_at"
        return "worked_at|studied_at"

    @property
    def entity_id(self) -> str:
        return "toString(e.entity.id)" if self.source_slots else "e.entity.id"


DEFAULT_MODEL = GraphQueryModel()
SOURCE_SLOT_MODEL = GraphQueryModel(source_slots=True)


def _pair(
    scope: RelationScope,
    month: int,
    anchor: str,
    other: str,
    extra: str = "",
    *,
    bounded_endpoints: bool = True,
    model: GraphQueryModel = DEFAULT_MODEL,
) -> str:
    start_column = "start_date" if model.source_slots else "start_month"
    end_column = "end_date" if model.source_slots else "end_month"
    edge = model.edge_pattern(scope)
    end_x = f"CASE WHEN x.is_current THEN {month} ELSE x.{end_column} END"
    end_y = f"CASE WHEN y.is_current THEN {month} ELSE y.{end_column} END"
    known = (
        f"x.{start_column} IS NOT NULL AND y.{start_column} IS NOT NULL "
        f"AND ({end_x}) IS NOT NULL AND ({end_y}) IS NOT NULL"
    )
    lo = (
        f"CASE WHEN x.{start_column} >= y.{start_column} "
        f"THEN x.{start_column} ELSE y.{start_column} END"
    )
    hi = f"CASE WHEN ({end_x}) <= ({end_y}) THEN ({end_x}) ELSE ({end_y}) END"
    if scope.relation_start_month is not None:
        lo = (
            f"CASE WHEN ({lo}) >= {scope.relation_start_month} "
            f"THEN ({lo}) ELSE {scope.relation_start_month} END"
        )
    if scope.relation_end_month is not None:
        hi = (
            f"CASE WHEN ({hi}) <= {scope.relation_end_month} "
            f"THEN ({hi}) ELSE {scope.relation_end_month} END"
        )
    organization = (
        f" AND {model.entity_id} IN " + literal(scope.relation_organization_ids)
        if scope.relation_organization_ids
        else ""
    )
    kind = ""
    if scope.relation_type == "same_school":
        kind = ' AND x.kind == "education"'
    elif scope.relation_type in {"same_company", "same_company_overlap"}:
        kind = ' AND x.kind == "employment"'
    # 两端已知时分别从人物读取经历，再在图内按实体连接。
    # 不能让规划器从热门公司反向展开全体人员后再过滤已知端点。
    pattern = (
        f"MATCH (a)-[x:{edge}]->(e) WHERE {anchor} AND a.person.active AND x.active "
        f"WITH a,x,e MATCH (b)-[y:{edge}]->(f) "
        f"WHERE {other} AND id(e) == id(f) AND b.person.active "
        if bounded_endpoints
        else f"MATCH (a)-[x:{edge}]->(e)<-[y:{edge}]-(b) "
        f"WHERE {anchor} AND {other} AND a.person.active AND b.person.active "
    )
    statement = (
        pattern + "AND x.active AND y.active AND x.kind == y.kind "
        'AND ((x.kind == "employment" AND e.entity.kind == "organization") '
        'OR (x.kind == "education" AND e.entity.kind == "school"))'
        + organization
        + kind
        + extra
        + f" WITH a,b,e,x,y,({known}) AS known,({lo}) AS lo,({hi}) AS hi "
        "WITH a,b,e,x,y,known,lo,hi,"
        "((hi / 100 - lo / 100) * 12 + hi % 100 - lo % 100 + 1) AS months "
        "WITH a,b,e,x,y,lo,hi,months,"
        '(x.kind == "employment" AND known AND lo <= hi) AS overlapping '
    )
    if scope.relation_type == "same_company_overlap":
        statement += f"WHERE overlapping AND months >= {scope.min_overlap_months or 1} "
    return statement


def candidate_query(
    request: PathRequest,
    month: int,
    after: str = "",
    page_size: int = 128,
    model: GraphQueryModel = DEFAULT_MODEL,
) -> str:
    """先按图内去重的实体邻接分页，避免重复任职把热门公司反复展开。"""
    if model.source_slots:
        slot_other = (
            "b.person.id > "
            + literal(after)
            + " AND id(b) NOT IN "
            + literal([request.reference_id, request.candidate_id])
        )
        if request.intermediate_source:
            slot_other += " AND id(b) STARTS WITH " + literal(f"p:{request.intermediate_source}:")
        return (
            _pair(
                request.scope,
                month,
                "id(a) == " + literal(request.reference_id),
                slot_other,
                bounded_endpoints=False,
                model=model,
            )
            + f"RETURN DISTINCT b.person.id AS middle ORDER BY middle LIMIT {page_size + 1}"
        )
    conditions = [
        f"id(a) == {literal(vid('p', request.reference_id))}",
        "a.person.active",
        "x.active",
    ]
    scope = request.scope
    if scope.relation_type == "same_school":
        conditions.append('x.kind == "education"')
    elif scope.relation_type in {"same_company", "same_company_overlap"}:
        conditions.append('x.kind == "employment"')
    if scope.relation_organization_ids:
        conditions.append("e.entity.id IN " + literal(scope.relation_organization_ids))
    if scope.relation_type == "same_company_overlap":
        end = f"CASE WHEN x.is_current THEN {month} ELSE x.end_month END"
        lo = "x.start_month"
        hi = f"({end})"
        if scope.relation_start_month is not None:
            lo = (
                f"CASE WHEN x.start_month >= {scope.relation_start_month} "
                f"THEN x.start_month ELSE {scope.relation_start_month} END"
            )
        if scope.relation_end_month is not None:
            hi = (
                f"CASE WHEN ({end}) <= {scope.relation_end_month} "
                f"THEN ({end}) ELSE {scope.relation_end_month} END"
            )
        conditions.extend(
            [
                "x.start_month IS NOT NULL",
                f"({end}) IS NOT NULL",
                f"({lo}) <= ({hi})",
                f"((({hi}) / 100 - ({lo}) / 100) * 12 + "
                f"({hi}) % 100 - ({lo}) % 100 + 1) >= {scope.min_overlap_months or 1}",
            ]
        )
    other = [
        "b.person.active",
        "b.person.id > " + literal(after),
        "id(b) NOT IN " + literal([vid("p", request.reference_id), vid("p", request.candidate_id)]),
    ]
    if request.intermediate_source:
        other.append(f"b.person.{request.intermediate_source}")
    return (
        "MATCH (a)-[x:experience]->(e) WHERE "
        + " AND ".join(conditions)
        + " WITH DISTINCT e MATCH (b)-[member:affiliated]->(e) WHERE "
        + " AND ".join(other)
        + f" RETURN DISTINCT b.person.id AS middle ORDER BY middle LIMIT {page_size + 1}"
    )


def qualified_query(
    request: PathRequest, month: int, candidates: list[str], model: GraphQueryModel = DEFAULT_MODEL
) -> str:
    return (
        _pair(
            request.scope,
            month,
            f"id(a) == {literal(model.person_vid(request.reference_id))}",
            "id(b) IN " + literal([model.person_vid(p) for p in candidates]),
            model=model,
        )
        + "RETURN DISTINCT b.person.id AS middle ORDER BY middle "
        + f"LIMIT {len(candidates)}"
    )


def connected_query(
    request: PathRequest, month: int, candidates: list[str], model: GraphQueryModel = DEFAULT_MODEL
) -> str:
    # 从另一端在图内匹配，候选范围由前一个图查询产生，不调用 SQL 资格查询。
    return (
        _pair(
            request.scope,
            month,
            f"id(a) == {literal(model.person_vid(request.candidate_id))}",
            "id(b) IN " + literal([model.person_vid(p) for p in candidates]),
            model=model,
        )
        + "RETURN DISTINCT b.person.id AS middle ORDER BY middle "
        + f"LIMIT {request.limits.path_limit + 1}"
    )


def evidence_query(
    request: PathRequest,
    month: int,
    pairs: list[tuple[str, str]],
    model: GraphQueryModel = DEFAULT_MODEL,
) -> str:
    statements = []
    for left, right in pairs:
        statement = _pair(
            request.scope,
            month,
            f"id(a) == {literal(model.person_vid(left))}",
            f"id(b) == {literal(model.person_vid(right))}",
            model=model,
        )
        statement += (
            f"RETURN {literal(left)} AS left_person, {literal(right)} AS right_person, "
            f"{model.entity_id} AS entity_id,x.fact_id AS left_fact,y.fact_id AS right_fact,"
            'CASE WHEN x.kind == "education" THEN "same_school" '
            'WHEN overlapping THEN "same_company_overlap" ELSE "same_company" END AS kind, '
            "CASE WHEN overlapping THEN lo ELSE NULL END AS start_month, "
            "CASE WHEN overlapping THEN hi ELSE NULL END AS end_month, "
            "CASE WHEN overlapping THEN months ELSE NULL END AS months, "
            "properties(x) AS left_properties,properties(y) AS right_properties "
        )
        if model.source_slots:
            statement += ",rank(x) AS left_rank,rank(y) AS right_rank "
        statement += f"ORDER BY left_fact,right_fact LIMIT {request.limits.evidence_limit + 1}"
        statements.append(statement)
    return " UNION ALL ".join(statements)
