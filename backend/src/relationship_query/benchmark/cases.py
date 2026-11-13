from dataclasses import dataclass, field


@dataclass
class Case:
    name: str
    method: str
    path: str
    body: dict[str, object] | None = None
    after: str | None = None
    description: str = ""
    notes: list[str] = field(default_factory=list)


def cases(size: int) -> list[Case]:
    def entity(name: str, filters: dict[str, object]) -> Case:
        return Case(name, "POST", "/api/v1/persons/search", filters)

    def person(name: str, reference: int, **filters: object) -> Case:
        return Case(
            name,
            "POST",
            f"/api/v1/persons/p:{reference:06d}/relations/search",
            {"relation_type": "same_company_overlap", **filters},
        )

    return [
        Case("meta", "GET", "/api/v1/meta"),
        Case("name_prefix", "GET", "/api/v1/persons/suggest?q=模拟人物0000&limit=20"),
        Case("name_miss", "GET", "/api/v1/persons/suggest?q=不存在虚构姓名&limit=20"),
        Case(
            "entity_alias",
            "GET",
            "/api/v1/entities/suggest?type=organization&q=虚构企业0999&limit=20",
        ),
        entity("entity_ordinary", {"organization_ids": ["org:0999"]}),
        entity("entity_hot_company", {"organization_ids": ["org:hot"]}),
        entity("entity_hot_school", {"school_ids": ["school:hot"]}),
        entity("company_role", {"organization_ids": ["org:0999"], "role_ids": ["role:01"]}),
        entity(
            "multi_intersection",
            {
                "organization_ids": ["org:hot"],
                "school_ids": ["school:003"],
                "role_ids": ["role:02"],
                "source": "expert",
            },
        ),
        entity(
            "empty_intersection",
            {"organization_ids": ["org:anchor-a"], "role_ids": ["role:unused"]},
        ),
        Case(
            "deep_cursor",
            "POST",
            "/api/v1/persons/search",
            {"organization_ids": ["org:hot"]},
            after=f"p:{int(size * 0.9):06d}",
            notes=["直接构造合法的 90% 位置游标，不包含前面各页的读取成本"],
        ),
        person("person_ordinary", 1),
        person("person_hot", 4),
        person("person_long", 5),
        person(
            "person_scoped",
            4,
            relation_start_month=202001,
            relation_end_month=202212,
            min_overlap_months=12,
        ),
        Case("facts_long", "GET", "/api/v1/persons/p:000005/facts"),
        Case(
            "compare_long",
            "POST",
            "/api/v1/persons/compare",
            {"reference_id": "p:000005", "candidate_id": "p:001005"},
        ),
        Case(
            "path_ordinary",
            "POST",
            "/api/v1/relations/paths",
            {
                "reference_id": "p:000001",
                "candidate_id": "p:000007",
                "scope": {"relation_type": "same_company_overlap"},
            },
        ),
        Case(
            "path_hot",
            "POST",
            "/api/v1/relations/paths",
            {
                "reference_id": "p:000004",
                "candidate_id": "p:000005",
                "scope": {"relation_type": "same_company_overlap"},
            },
        ),
        Case(
            "path_long",
            "POST",
            "/api/v1/relations/paths",
            {
                "reference_id": "p:000005",
                "candidate_id": "p:001005",
                "scope": {"relation_type": "same_company_overlap"},
            },
        ),
        Case(
            "path_empty",
            "POST",
            "/api/v1/relations/paths",
            {
                "reference_id": "p:000001",
                "candidate_id": "p:000003",
                "scope": {"relation_type": "same_company_overlap"},
            },
        ),
    ]
