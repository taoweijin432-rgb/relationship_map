from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from relationship_query.domain.models import (
    Entity,
    EntityType,
    Fact,
    Month,
    Person,
    RelationType,
    Source,
)
from relationship_query.domain.path_budget import PathLimit


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetadataFields(TypedDict):
    data_mode: Literal["mock", "real"]
    data_version: str
    reference_month: int


class DatasetCounts(TypedDict):
    person_count: int
    expert_count: int
    resume_count: int
    entity_count: int
    fact_count: int


class Metadata(Contract):
    data_mode: Literal["mock", "real"] = "mock"
    data_version: str
    reference_month: Month


class MetaResponse(Metadata):
    person_display: Literal["snapshot", "mysql-live"] = "snapshot"
    max_relation_hops: int = 1
    person_count: int
    expert_count: int
    resume_count: int
    entity_count: int
    fact_count: int
    storage: Literal[
        "sqlite-demo",
        "mysql-demo",
        "mysql-source-slots",
        "mysql-uuid-source",
        "sqlite-numeric-source",
    ] = "sqlite-demo"
    graph_model: str | None = None
    relation_backend: Literal["sql", "nebula-materialized"] = "sql"


class RelationScope(Contract):
    relation_type: RelationType | None = None
    require_same_school: bool = Field(default=False, strict=True)
    relation_organization_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=50
    )
    relation_start_month: Month | None = None
    relation_end_month: Month | None = None
    min_overlap_months: int | None = Field(default=None, ge=1, le=2412)

    @model_validator(mode="after")
    def check_scope(self) -> "RelationScope":
        if self.require_same_school and self.relation_type != "same_major":
            raise ValueError("同校前提仅用于同专业关系")
        if (
            self.relation_start_month
            and self.relation_end_month
            and self.relation_start_month > self.relation_end_month
        ):
            raise ValueError("共同任职开始月份不能晚于结束月份")
        self.relation_organization_ids = sorted(set(self.relation_organization_ids))
        if self.relation_organization_ids and self.relation_type not in (
            "same_company",
            "same_company_overlap",
        ):
            raise ValueError("共同公司筛选仅用于同公司关系")
        if (
            any(
                v is not None
                for v in (
                    self.relation_start_month,
                    self.relation_end_month,
                    self.min_overlap_months,
                )
            )
            and self.relation_type != "same_company_overlap"
        ):
            raise ValueError("共同任职时间窗和最短月数仅用于同公司同期关系")
        return self


class SearchRequest(RelationScope):
    max_hops: int = Field(default=1, ge=1, le=4, strict=True)
    major_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=50
    )
    position_titles: list[Annotated[str, Field(min_length=1, max_length=255)]] = Field(
        default_factory=list, max_length=50
    )
    organization_id: str | None = Field(default=None, max_length=100)
    school_id: str | None = Field(default=None, max_length=100)
    role_id: str | None = Field(default=None, max_length=100)
    organization_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=50
    )
    school_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=50
    )
    role_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=50
    )
    source: Source | None = None
    start_month: Month | None = None
    end_month: Month | None = None
    cursor: str | None = Field(default=None, max_length=2048)
    page_size: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def check_range(self) -> "SearchRequest":
        self.position_titles = sorted(set(self.position_titles))
        self.major_ids = sorted(set(self.major_ids))
        if self.start_month and self.end_month and self.start_month > self.end_month:
            raise ValueError("筛选开始月份不能晚于结束月份")
        for single, multiple in (
            ("organization_id", "organization_ids"),
            ("school_id", "school_ids"),
            ("role_id", "role_ids"),
        ):
            legacy = getattr(self, single)
            values = sorted(set(getattr(self, multiple)) | ({legacy} if legacy else set()))
            if len(values) > 50:
                raise ValueError("每类最多选择 50 个不同实体")
            setattr(self, multiple, values)
        return self


class ExpandRequest(Contract):
    person_id: str = Field(min_length=1, max_length=100)
    filters: SearchRequest = Field(default_factory=SearchRequest)
    existing_node_ids: list[str] = Field(default_factory=list, max_length=100)
    existing_edge_ids: list[str] = Field(default_factory=list, max_length=200)


class FactView(Contract):
    fact: Fact
    entity: Entity
    role: Entity | None = None


class Evidence(Contract):
    id: str
    relation_type: RelationType
    label: str
    entity: Entity
    reference: FactView
    candidate: FactView
    overlap_start: int | None = None
    overlap_end: int | None = None
    overlap_months: int | None = None
    explanation: str


class RelationSummary(Contract):
    type: RelationType
    label: str
    entity_name: str
    evidence_id: str


class PersonItem(Contract):
    person: Person
    relations: list[RelationSummary] = Field(default_factory=list)
    connection: "ConnectionSummary | None" = None


class ConnectionSummary(Contract):
    hop_count: int = Field(ge=1, le=4)
    person_ids: list[str]


class ConnectionDetail(ConnectionSummary):
    persons: list[Person]
    segments: list["PathSegment"]


class GraphNode(Contract):
    id: str
    type: Literal["person", "organization", "school", "major"]
    label: str
    is_reference: bool = False


class GraphEdge(Contract):
    id: str
    source: str
    target: str
    label: str
    fact_id: str


class GraphData(Contract):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = False
    truncation_reason: str | None = None


class SearchResponse(Metadata):
    applied_filters: SearchRequest
    items: list[PersonItem]
    reference: Person | None = None
    next_cursor: str | None
    has_more: bool
    graph: GraphData


class ExpandResponse(Metadata):
    graph: GraphData
    has_more: bool


class PersonsResponse(Metadata):
    items: list[Person]


class EntitiesResponse(Metadata):
    items: list[Entity]


class FactsResponse(Metadata):
    person: Person
    items: list[FactView]


class EvidenceResponse(Metadata):
    reference: Person
    candidate: Person
    items: list[Evidence]
    connection: ConnectionDetail | None = None


class ScopedEvidenceRequest(Contract):
    reference_id: str = Field(min_length=1, max_length=100)
    candidate_id: str = Field(min_length=1, max_length=100)
    filters: SearchRequest = Field(default_factory=SearchRequest)


class EntityResponse(Metadata):
    entity: Entity


class ExportRequest(Contract):
    reference_id: str | None = Field(default=None, min_length=1, max_length=100)
    filters: SearchRequest
    data_version: str = Field(min_length=1, max_length=200)
    expected_person_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        max_length=50
    )


class ExportItem(PersonItem):
    evidence: list[Evidence]
    facts: list[FactView]
    connection_detail: ConnectionDetail | None = None


class ExportResponse(Metadata):
    scope: Literal["current_page"] = "current_page"
    facts_scope: Literal["all_active_person_facts"] = "all_active_person_facts"
    filters: SearchRequest
    reference: Person | None
    items: list[ExportItem]
    has_more: bool


class ComparisonRequest(Contract):
    reference_id: str = Field(min_length=1, max_length=100)
    candidate_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_people(self) -> "ComparisonRequest":
        if self.reference_id == self.candidate_id:
            raise ValueError("请选择两位不同的人物进行对比")
        return self


class ComparisonResponse(Metadata):
    reference: Person
    candidate: Person
    reference_facts: list[FactView]
    candidate_facts: list[FactView]
    evidence: list[Evidence]


class PathLimits(Contract):
    candidate_limit: int = Field(default=200, ge=1, le=500)
    path_limit: int = Field(default=10, ge=1, le=20)
    fact_limit: int = Field(default=2000, ge=1, le=5000)
    evidence_limit: int = Field(default=20, ge=1, le=100)
    time_budget_ms: int = Field(default=1500, ge=10, le=3000)


class PathRequest(ComparisonRequest):
    scope: RelationScope = Field(default_factory=RelationScope)
    intermediate_source: Source | None = None
    limits: PathLimits = Field(default_factory=PathLimits)


class PathSegment(Contract):
    id: str
    from_person: Person
    to_person: Person
    evidence: list[Evidence]
    evidence_truncated: bool = False


class PersonPath(Contract):
    id: str
    intermediate: Person
    segments: tuple[PathSegment, PathSegment]


class PathStats(Contract):
    candidates_examined: int = 0
    fact_rows_loaded: int = 0
    evidence_pairs_examined: int = 0
    elapsed_ms: float = 0
    graph_calls: int = 0
    graph_rows: int = 0
    graph_candidates: int = 0


class PathResponse(Metadata):
    query_backend: Literal["sql", "nebula_sql", "nebula"] = "sql"
    projection_id: str | None = None
    scope: RelationScope
    intermediate_source: Source | None
    limits: PathLimits
    reference: Person
    candidate: Person
    direct: PathSegment | None
    direct_checked: bool
    paths: list[PersonPath]
    search_complete: bool
    truncated: bool
    truncation_reasons: list[PathLimit]
    status: Literal["found", "not_found", "limited"]
    message: str
    stats: PathStats


class ErrorResponse(Contract):
    code: str
    message: str
    data_mode: Literal["mock", "real"] = "mock"
    data_version: str | None = None


class HealthResponse(Contract):
    status: Literal["ok"] = "ok"
    data_mode: Literal["mock", "real"] = "mock"
    data_version: str


EntityKind = EntityType
