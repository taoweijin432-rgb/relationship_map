from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from relationship_query.api.dispatch import QueryDispatch
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

router = APIRouter(prefix="/api/v1")


async def service(request: Request) -> QueryDispatch:
    return cast(QueryDispatch, request.app.state.query_dispatch)


Service = Annotated[QueryDispatch, Depends(service)]


@router.post("/relations/paths", response_model=PathResponse)
async def find_paths(body: PathRequest, query: Service) -> PathResponse:
    return await query.find_paths(body)


@router.get("/health", response_model=HealthResponse)
async def health(query: Service) -> HealthResponse:
    return HealthResponse(
        data_version=query.query.repository.version, data_mode=query.query.metadata()["data_mode"]
    )


@router.get("/meta", response_model=MetaResponse)
async def meta(query: Service) -> MetaResponse:
    return MetaResponse(
        person_display=getattr(query.query.repository, "person_display", "snapshot"),
        max_relation_hops=4
        if getattr(query.query.repository, "storage", "")
        in {"mysql-uuid-source", "sqlite-numeric-source"}
        else 1,
        **query.query.metadata(),
        **query.counts,
        storage=getattr(query.query.repository, "storage", "sqlite-demo"),
        graph_model=getattr(getattr(query.query.repository, "manifest", None), "model", None),
        relation_backend="nebula-materialized"
        if getattr(query.query.repository, "storage", "")
        in {"mysql-uuid-source", "sqlite-numeric-source"}
        else "sql",
    )


@router.get("/persons/suggest", response_model=PersonsResponse)
async def person_suggestions(
    query: Service,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
) -> PersonsResponse:
    return await query.run(
        "light",
        lambda: PersonsResponse(
            **query.query.metadata(), items=query.query.repository.suggest_people(q.strip(), limit)
        ),
    )


@router.get("/entities/suggest", response_model=EntitiesResponse)
async def entity_suggestions(
    query: Service,
    type: EntityKind,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
) -> EntitiesResponse:
    return await query.run(
        "light",
        lambda: EntitiesResponse(
            **query.query.metadata(),
            items=query.query.repository.suggest_entities(type, q.strip(), limit),
        ),
    )


@router.get("/entities/{entity_id}", response_model=EntityResponse)
async def entity_details(entity_id: str, query: Service) -> EntityResponse:
    return await query.run("light", lambda: query.query.entity(entity_id))


@router.post("/exports/persons", response_model=ExportResponse)
async def export_people(body: ExportRequest, query: Service) -> ExportResponse:
    return await query.export(body)


@router.post("/relations/evidence/search", response_model=EvidenceResponse)
async def scoped_evidence(body: ScopedEvidenceRequest, query: Service) -> EvidenceResponse:
    return await query.evidence(body.reference_id, body.candidate_id, body.filters)


@router.post("/persons/search", response_model=SearchResponse)
async def search_people(body: SearchRequest, query: Service) -> SearchResponse:
    return await query.search(body)


@router.post("/persons/compare", response_model=ComparisonResponse)
async def compare_people(body: ComparisonRequest, query: Service) -> ComparisonResponse:
    return await query.compare(body.reference_id, body.candidate_id)


@router.post("/persons/{person_id}/relations/search", response_model=SearchResponse)
async def related_people(person_id: str, body: SearchRequest, query: Service) -> SearchResponse:
    return await query.search(body, person_id)


@router.post("/graph/expand", response_model=ExpandResponse)
async def expand_graph(body: ExpandRequest, query: Service) -> ExpandResponse:
    return await query.expand(body)


@router.get("/persons/{person_id}/facts", response_model=FactsResponse)
async def person_facts(person_id: str, query: Service) -> FactsResponse:
    return await query.run("light", lambda: query.query.facts(person_id))


@router.get("/relations/evidence", response_model=EvidenceResponse)
async def relation_evidence(
    query: Service, reference_id: str, candidate_id: str
) -> EvidenceResponse:
    return await query.evidence(reference_id, candidate_id)
