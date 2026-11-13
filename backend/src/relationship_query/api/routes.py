from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from relationship_query.contracts import (
    ComparisonRequest,
    ComparisonResponse,
    EntitiesResponse,
    EntityKind,
    EntityResponse,
    EvidenceResponse,
    ExpandRequest,
    ExpandResponse,
    ExportRequest,
    ExportResponse,
    FactsResponse,
    HealthResponse,
    MetaResponse,
    PathRequest,
    PathResponse,
    PersonsResponse,
    ScopedEvidenceRequest,
    SearchRequest,
    SearchResponse,
)
from relationship_query.services.paths import PathService
from relationship_query.services.query import QueryService

router = APIRouter(prefix="/api/v1")


def service(request: Request) -> QueryService:
    return cast(QueryService, request.app.state.query_service)


Service = Annotated[QueryService, Depends(service)]


def paths_service(request: Request) -> PathService:
    return cast(PathService, request.app.state.path_service)


@router.post("/relations/paths", response_model=PathResponse)
def find_paths(
    body: PathRequest, query: Annotated[PathService, Depends(paths_service)]
) -> PathResponse:
    return query.search(body)


@router.get("/health", response_model=HealthResponse)
def health(query: Service) -> HealthResponse:
    return HealthResponse(
        data_version=query.repository.version, data_mode=query.metadata()["data_mode"]
    )


@router.get("/meta", response_model=MetaResponse)
def meta(query: Service) -> MetaResponse:
    return MetaResponse(
        person_display=getattr(query.repository, "person_display", "snapshot"),
        max_relation_hops=4
        if getattr(query.repository, "storage", "")
        in {"mysql-uuid-source", "sqlite-numeric-source"}
        else 1,
        **query.metadata(),
        **query.repository.counts(),
        storage=getattr(query.repository, "storage", "sqlite-demo"),
        graph_model=getattr(getattr(query.repository, "manifest", None), "model", None),
        relation_backend="nebula-materialized"
        if getattr(query.repository, "storage", "")
        in {"mysql-uuid-source", "sqlite-numeric-source"}
        else "sql",
    )


@router.get("/persons/suggest", response_model=PersonsResponse)
def person_suggestions(
    query: Service,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
) -> PersonsResponse:
    return PersonsResponse(
        **query.metadata(), items=query.repository.suggest_people(q.strip(), limit)
    )


@router.get("/entities/suggest", response_model=EntitiesResponse)
def entity_suggestions(
    query: Service,
    type: EntityKind,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
) -> EntitiesResponse:
    return EntitiesResponse(
        **query.metadata(), items=query.repository.suggest_entities(type, q.strip(), limit)
    )


@router.get("/entities/{entity_id}", response_model=EntityResponse)
def entity_details(entity_id: str, query: Service) -> EntityResponse:
    return query.entity(entity_id)


@router.post("/exports/persons", response_model=ExportResponse)
def export_people(body: ExportRequest, query: Service) -> ExportResponse:
    return query.export_page(body)


@router.post("/relations/evidence/search", response_model=EvidenceResponse)
def scoped_evidence(body: ScopedEvidenceRequest, query: Service) -> EvidenceResponse:
    return query.evidence(body.reference_id, body.candidate_id, body.filters)


@router.post("/persons/search", response_model=SearchResponse)
def search_people(body: SearchRequest, query: Service) -> SearchResponse:
    return query.search(body)


@router.post("/persons/compare", response_model=ComparisonResponse)
def compare_people(body: ComparisonRequest, query: Service) -> ComparisonResponse:
    return query.compare(body.reference_id, body.candidate_id)


@router.post("/persons/{person_id}/relations/search", response_model=SearchResponse)
def related_people(person_id: str, body: SearchRequest, query: Service) -> SearchResponse:
    return query.search(body, person_id)


@router.post("/graph/expand", response_model=ExpandResponse)
def expand_graph(body: ExpandRequest, query: Service) -> ExpandResponse:
    return query.expand(body)


@router.get("/persons/{person_id}/facts", response_model=FactsResponse)
def person_facts(person_id: str, query: Service) -> FactsResponse:
    return query.facts(person_id)


@router.get("/relations/evidence", response_model=EvidenceResponse)
def relation_evidence(query: Service, reference_id: str, candidate_id: str) -> EvidenceResponse:
    return query.evidence(reference_id, candidate_id)
