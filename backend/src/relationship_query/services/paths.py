from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from time import monotonic
from typing import Literal

from relationship_query.contracts import (
    FactView,
    PathRequest,
    PathResponse,
    PathSegment,
    PathStats,
    PersonPath,
)
from relationship_query.domain.models import Person
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded, PathLimit
from relationship_query.runtime.diagnostics import traced
from relationship_query.services.evidence import build_evidence
from relationship_query.services.ports import PathReader, PathRepository
from relationship_query.services.query import QueryError, QueryService


@dataclass
class _SearchState:
    request: PathRequest
    budget: PathBudget
    reference: Person
    candidate: Person
    direct: PathSegment | None = None
    direct_checked: bool = False
    paths: list[PersonPath] = field(default_factory=list)
    reasons: set[PathLimit] = field(default_factory=set)
    candidates_examined: int = 0


class PathService:
    def __init__(
        self,
        repository: PathRepository,
        queries: QueryService,
        *,
        clock: Callable[[], float] = monotonic,
        query_backend: Literal["sql", "nebula_sql", "nebula"] = "sql",
        projection_id: str | None = None,
    ) -> None:
        self.repository, self.queries, self.clock = repository, queries, clock
        self.query_backend, self.projection_id = query_backend, projection_id

    @traced("PathService.search")
    def search(self, request: PathRequest) -> PathResponse:
        state = self._new_state(request)
        budget = state.budget
        try:
            with self.repository.session(budget) as reader:
                self._search(reader, state)
                budget.check()
        except PathBudgetExceeded as exc:
            state.reasons.add(exc.reason)
        state.reasons.update(budget.candidate_reasons)
        return self._response(state)

    def _new_state(self, request: PathRequest) -> _SearchState:
        if request.scope.relation_type == "same_major" and getattr(
            self.queries.repository, "storage", ""
        ) not in {"mysql-uuid-source", "sqlite-numeric-source"}:
            raise QueryError("UNSUPPORTED_RELATION", "同专业路径需要启用图内人物关系")
        # 定位输入只读固定 ID；执行预算从开始读取事实起生效，不承诺 HTTP 硬时限。
        reference = self.queries.require_person(request.reference_id)
        candidate = self.queries.require_person(request.candidate_id)
        selected = request.scope.relation_organization_ids
        if {
            e.id for e in self.queries.repository.get_entities(selected) if e.type == "organization"
        } != set(selected):
            raise QueryError("INVALID_ENTITY", "共同公司不存在或类型不正确")
        budget = PathBudget(
            request.limits.time_budget_ms, request.limits.fact_limit, clock=self.clock
        )
        return _SearchState(request, budget, reference, candidate)

    def _search(self, reader: PathReader, state: _SearchState) -> None:
        views = self._group(reader.fact_views([state.reference.id, state.candidate.id]))
        left, right = views[state.reference.id], views[state.candidate.id]
        state.direct = self._segment(state, state.reference, state.candidate, left, right)
        state.direct_checked = True
        self._record_evidence_limit(state, state.direct)
        if not left or not right:
            return
        candidates = reader.candidates(state.request)
        if len(candidates) > state.request.limits.candidate_limit:
            state.reasons.add("candidate_limit")
        ids = candidates[: state.request.limits.candidate_limit]
        for offset in range(0, len(ids), 10):
            batch = ids[offset : offset + 10]
            middle_views = self._group(reader.fact_views(batch))
            persons = reader.persons(batch)
            for person_id in batch:
                state.budget.check()
                state.candidates_examined += 1
                if self._add_path(state, persons[person_id], left, middle_views[person_id], right):
                    return

    def _add_path(
        self,
        state: _SearchState,
        person: Person,
        left: list[FactView],
        middle: list[FactView],
        right: list[FactView],
    ) -> bool:
        first = self._segment(state, state.reference, person, left, middle)
        if first is None:
            return False
        second = self._segment(state, person, state.candidate, middle, right)
        if second is None:
            return False
        if len(state.paths) >= state.request.limits.path_limit:
            state.reasons.add("path_limit")
            return True
        self._record_evidence_limit(state, first, second)
        key = f"{state.reference.id}|{person.id}|{state.candidate.id}"
        state.paths.append(
            PersonPath(
                id="path:" + sha256(key.encode()).hexdigest()[:24],
                intermediate=person,
                segments=(first, second),
            )
        )
        return False

    @traced("PathService.segment")
    def _segment(
        self,
        state: _SearchState,
        left: Person,
        right: Person,
        left_views: list[FactView],
        right_views: list[FactView],
    ) -> PathSegment | None:
        scope = state.request.scope
        limit = state.request.limits.evidence_limit
        evidence = build_evidence(
            left_views,
            right_views,
            self.repository.reference_month,
            scope.relation_type,
            scope,
            state.budget.check_pair,
            limit + 1,
        )
        if not evidence:
            return None
        return PathSegment(
            id=f"segment:{left.id}|{right.id}",
            from_person=left,
            to_person=right,
            evidence=evidence[:limit],
            evidence_truncated=len(evidence) > limit,
        )

    @staticmethod
    def _group(views: list[FactView]) -> dict[str, list[FactView]]:
        result: dict[str, list[FactView]] = defaultdict(list)
        for view in views:
            result[view.fact.person_id].append(view)
        return result

    @staticmethod
    def _record_evidence_limit(state: _SearchState, *segments: PathSegment | None) -> None:
        if any(segment and segment.evidence_truncated for segment in segments):
            state.reasons.add("evidence_limit")

    def _response(self, state: _SearchState) -> PathResponse:
        complete = not (state.reasons - {"evidence_limit"}) and state.direct_checked
        found = bool(state.direct or state.paths)
        truncated = bool(state.reasons)
        status: Literal["found", "not_found", "limited"] = (
            "found" if found else "not_found" if complete else "limited"
        )
        message = (
            "已发现连接链；部分搜索或证据展示受限，请核对范围说明。"
            if found and truncated
            else "已发现可核实的经历连接链；各段分别判断，不推断实际认识。"
            if found
            else "所选规则下未发现直接或经过一位中间人物的连接链。"
            if complete
            else "搜索范围受限，尚不能判断是否存在连接链。"
        )
        return PathResponse(
            query_backend=self.query_backend,
            projection_id=self.projection_id,
            **self.queries.metadata(),
            scope=state.request.scope,
            intermediate_source=state.request.intermediate_source,
            limits=state.request.limits,
            reference=state.reference,
            candidate=state.candidate,
            direct=state.direct,
            direct_checked=state.direct_checked,
            paths=state.paths,
            search_complete=complete,
            truncated=truncated,
            truncation_reasons=sorted(state.reasons),
            status=status,
            message=message,
            stats=PathStats(
                candidates_examined=state.candidates_examined,
                fact_rows_loaded=state.budget.facts,
                evidence_pairs_examined=state.budget.pairs,
                elapsed_ms=state.budget.elapsed_ms(),
                graph_calls=state.budget.graph_calls,
                graph_rows=state.budget.graph_rows,
                graph_candidates=state.budget.graph_candidates,
            ),
        )
