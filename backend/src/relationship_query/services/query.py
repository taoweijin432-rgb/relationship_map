import base64
import binascii
import hashlib
import json
from collections import defaultdict

from relationship_query.contracts import (
    ComparisonResponse,
    EntityResponse,
    Evidence,
    EvidenceResponse,
    ExpandRequest,
    ExpandResponse,
    ExportItem,
    ExportRequest,
    ExportResponse,
    FactsResponse,
    FactView,
    MetadataFields,
    PersonItem,
    RelationScope,
    RelationSummary,
    SearchRequest,
    SearchResponse,
)
from relationship_query.domain.models import Person, RelationType
from relationship_query.runtime.diagnostics import traced
from relationship_query.services.evidence import build_evidence
from relationship_query.services.graph import build_graph
from relationship_query.services.ports import QueryRepository
from relationship_query.services.query_plan import DirectPage, PersonPagePlan


class QueryError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class QueryService:
    def __init__(self, repository: QueryRepository) -> None:
        self.repository = repository

    def _build_evidence(
        self,
        left: list[FactView],
        right: list[FactView],
        reference_month: int,
        kind: RelationType | None = None,
        filters: RelationScope | None = None,
    ) -> list[Evidence]:
        return build_evidence(left, right, reference_month, kind, filters)

    def metadata(self) -> MetadataFields:
        return {
            "data_mode": getattr(self.repository, "data_mode", "mock"),
            "data_version": self.repository.version,
            "reference_month": self.repository.reference_month,
        }

    def require_person(self, person_id: str) -> Person:
        person = self.repository.person(person_id)
        if person is None:
            raise QueryError("PERSON_NOT_FOUND", "人物不存在或已失效", 404)
        return person

    def _validate_filters(self, request: SearchRequest, reference_id: str | None) -> None:
        if request.max_hops > 1:
            if reference_id is None:
                raise QueryError("REFERENCE_REQUIRED", "多跳关联查询需要参考人物")
            if getattr(self.repository, "storage", "") not in {
                "mysql-uuid-source",
                "sqlite-numeric-source",
            }:
                raise QueryError("UNSUPPORTED_MULTI_HOP", "当前数据模式支持1跳关联查询")
        if request.relation_type == "same_major" and getattr(
            self.repository, "storage", ""
        ) not in {"mysql-uuid-source", "sqlite-numeric-source"}:
            raise QueryError("UNSUPPORTED_RELATION", "同专业查询需要启用图内人物关系")
        groups = (
            (request.organization_ids, "organization"),
            (request.school_ids, "school"),
            (request.major_ids, "major"),
            (request.role_ids, "role"),
            (request.relation_organization_ids, "organization"),
        )
        entity_map = {
            e.id: e
            for e in self.repository.get_entities(
                [entity_id for ids, _ in groups for entity_id in ids]
            )
        }
        for ids, kind in groups:
            for entity_id in ids:
                entity = entity_map.get(entity_id)
                if entity is None or entity.type != kind:
                    raise QueryError("INVALID_ENTITY", "筛选实体不存在或类型不正确")
        if request.relation_type and reference_id is None:
            raise QueryError("REFERENCE_REQUIRED", "关系类型筛选需要参考人物")

    @traced("QueryService.search")
    def search(self, request: SearchRequest, reference_id: str | None = None) -> SearchResponse:
        return self._direct_page(request, reference_id).response

    @traced("QueryService.select_page")
    def select_page(self, request: SearchRequest, reference_id: str | None) -> PersonPagePlan:
        """选择与展示分离；计划仅含ID和分页状态，人物有效性仍需在线核对。"""
        self._validate_filters(request, reference_id)
        fingerprint = self._fingerprint(request, reference_id)
        after = self._decode_cursor(request.cursor, fingerprint) if request.cursor else None
        found = self.repository.search_ids(request, reference_id, after)
        ids, has_more = found[: request.page_size], len(found) > request.page_size
        return PersonPagePlan(
            self.repository.version,
            self.repository.reference_month,
            reference_id,
            fingerprint,
            tuple(ids),
            has_more,
            self._encode_cursor(ids[-1], fingerprint) if has_more else None,
        )

    def _direct_page(self, request: SearchRequest, reference_id: str | None) -> DirectPage:
        reference = self.require_person(reference_id) if reference_id else None
        plan = self.select_page(request, reference_id)
        ids = list(plan.ids)
        persons = sorted(self.repository.persons(ids), key=lambda p: p.id)
        views = self.repository.fact_views(ids + ([reference_id] if reference_id else []))
        proofs = (
            self._proofs([(reference_id, p.id) for p in persons], views, request)
            if reference_id
            else {}
        )
        items, graph_views = self._assemble(persons, views, request, reference_id, proofs)
        graph_persons = ([reference] if reference else []) + persons
        response = SearchResponse(
            **self.metadata(),
            applied_filters=request,
            items=items,
            reference=reference,
            has_more=plan.has_more,
            next_cursor=plan.next_cursor,
            graph=build_graph(graph_persons, graph_views, reference_id),
        )
        return DirectPage(response, views, graph_views, proofs)

    def _proofs(
        self, pairs: list[tuple[str, str]], views: list[FactView], scope: RelationScope
    ) -> dict[tuple[str, str], list[Evidence]]:
        by_person: dict[str, list[FactView]] = defaultdict(list)
        for view in views:
            by_person[view.fact.person_id].append(view)
        return {
            pair: self._build_evidence(
                by_person[pair[0]],
                by_person[pair[1]],
                self.repository.reference_month,
                scope.relation_type,
                scope,
            )
            for pair in pairs
        }

    @traced("QueryService.assemble")
    def _assemble(
        self,
        persons: list[Person],
        views: list[FactView],
        request: SearchRequest,
        reference_id: str | None,
        evidence: dict[tuple[str, str], list[Evidence]] | None = None,
    ) -> tuple[list[PersonItem], list[FactView]]:
        if reference_id is None:
            return [PersonItem(person=p) for p in persons], views
        if evidence is None:
            evidence = self._proofs([(reference_id, p.id) for p in persons], views, request)
        items, graph_views = [], {}
        for person in persons:
            summaries: dict[tuple[str, str], RelationSummary] = {}
            for ev in evidence.get((reference_id, person.id), []):
                summaries[(ev.relation_type, ev.entity.id)] = RelationSummary(
                    type=ev.relation_type,
                    label=ev.label,
                    entity_name=ev.entity.name,
                    evidence_id=ev.id,
                )
                graph_views[ev.reference.fact.id] = ev.reference
                graph_views[ev.candidate.fact.id] = ev.candidate
            items.append(PersonItem(person=person, relations=list(summaries.values())))
        return items, list(graph_views.values())

    @traced("QueryService.facts")
    def facts(self, person_id: str) -> FactsResponse:
        return FactsResponse(
            **self.metadata(),
            person=self.require_person(person_id),
            items=self.repository.fact_views([person_id]),
        )

    @traced("QueryService.evidence")
    def evidence(
        self, reference_id: str, candidate_id: str, filters: SearchRequest | None = None
    ) -> EvidenceResponse:
        reference, candidate = self.require_person(reference_id), self.require_person(candidate_id)
        if filters is not None:
            self._validate_filters(filters, reference_id)
        views = self.repository.fact_views([reference_id, candidate_id])
        evidence = (
            []
            if reference_id == candidate_id
            or (
                filters is not None
                and not self.repository.matches_person(filters, reference_id, candidate_id)
            )
            else self._build_evidence(
                [v for v in views if v.fact.person_id == reference_id],
                [v for v in views if v.fact.person_id == candidate_id],
                self.repository.reference_month,
                filters.relation_type if filters else None,
                filters,
            )
        )
        return EvidenceResponse(
            **self.metadata(), reference=reference, candidate=candidate, items=evidence
        )

    def entity(self, entity_id: str) -> EntityResponse:
        entity = self.repository.entity(entity_id)
        if entity is None:
            raise QueryError("ENTITY_NOT_FOUND", "实体不存在", 404)
        return EntityResponse(**self.metadata(), entity=entity)

    @traced("QueryService.export_page")
    def export_page(self, request: ExportRequest) -> ExportResponse:
        if request.data_version != self.repository.version:
            raise QueryError("STALE_EXPORT", "数据版本已变化，请重新查询后导出", 409)
        page = self._direct_page(request.filters, request.reference_id)
        result = page.response
        ids = [item.person.id for item in result.items]
        if ids != request.expected_person_ids:
            raise QueryError("STALE_EXPORT", "当前页人物已变化，请重新查询后导出", 409)
        views: dict[str, list[FactView]] = defaultdict(list)
        for view in page.facts:
            views[view.fact.person_id].append(view)
        items = [
            ExportItem(
                **item.model_dump(),
                facts=views[item.person.id],
                evidence=page.evidence.get((request.reference_id, item.person.id), [])
                if request.reference_id
                else [],
            )
            for item in result.items
        ]
        if sum(len(item.facts) + len(item.evidence) for item in items) > 5000:
            raise QueryError(
                "EXPORT_LIMIT", "当前页经历与证据超过 5000 条，请缩小每页人数或查询范围"
            )
        return ExportResponse(
            **self.metadata(),
            filters=request.filters,
            reference=result.reference,
            items=items,
            has_more=result.has_more,
        )

    @traced("QueryService.expand")
    def expand(self, request: ExpandRequest) -> ExpandResponse:
        filters = request.filters.model_copy(update={"page_size": 20, "cursor": None})
        page = self._direct_page(filters, request.person_id)
        result = page.response
        # 保留原展开流程的最后一次在线中心有效性检查。
        root = (
            self.require_person(request.person_id)
            if getattr(self.repository, "person_display", "snapshot") == "mysql-live"
            else result.reference
        )
        assert root is not None
        graph = build_graph(
            [root, *[i.person for i in result.items]],
            page.graph_facts,
            request.person_id,
            request.existing_node_ids,
            request.existing_edge_ids,
        )
        if result.has_more:
            graph = graph.model_copy(
                update={
                    "truncated": True,
                    "truncation_reason": graph.truncation_reason
                    or "本次仅展开前 20 位直接关联人物，可设为中心继续分页查询",
                }
            )
        return ExpandResponse(**self.metadata(), graph=graph, has_more=result.has_more)

    @traced("QueryService.compare")
    def compare(self, reference_id: str, candidate_id: str) -> ComparisonResponse:
        reference = self.require_person(reference_id)
        candidate = self.require_person(candidate_id)
        views = self.repository.fact_views([reference_id, candidate_id])
        left = [view for view in views if view.fact.person_id == reference_id]
        right = [view for view in views if view.fact.person_id == candidate_id]
        return ComparisonResponse(
            **self.metadata(),
            reference=reference,
            candidate=candidate,
            reference_facts=left,
            candidate_facts=right,
            evidence=self._build_evidence(left, right, self.repository.reference_month),
        )

    def _fingerprint(self, request: SearchRequest, reference_id: str | None) -> str:
        excluded = {"cursor", "page_size", "organization_id", "school_id", "role_id"}
        if not request.require_same_school:
            excluded.add("require_same_school")
        content = {
            "filters": request.model_dump(exclude=excluded),
            "reference": reference_id,
            "version": self.repository.version,
            "query_contract": "scoped-relations-v1",
        }
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _encode_cursor(after: str, fingerprint: str) -> str:
        return base64.urlsafe_b64encode(json.dumps([after, fingerprint]).encode()).decode()

    @staticmethod
    def _decode_cursor(cursor: str, fingerprint: str) -> str:
        try:
            payload = json.loads(base64.b64decode(cursor.encode(), altchars=b"-_", validate=True))
            if (
                not isinstance(payload, list)
                or len(payload) != 2
                or not isinstance(payload[0], str)
                or len(payload[0]) > 100
                or payload[1] != fingerprint
            ):
                raise ValueError("cursor context mismatch")
            return payload[0]
        except (ValueError, binascii.Error, UnicodeError) as exc:
            raise QueryError(
                "INVALID_CURSOR", "分页游标无效或查询条件、数据版本已变化，请重新查询"
            ) from exc
