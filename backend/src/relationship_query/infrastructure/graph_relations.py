"""原生图查询计算两端连接与关系证据，SQL 仅按 ID 读取人物／事实。"""

from pydantic import ValidationError

from relationship_query.contracts import FactView, PathRequest
from relationship_query.domain.graph_relations import GraphProof
from relationship_query.domain.models import Person
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.graph_client import GraphClient
from relationship_query.infrastructure.graph_model import vid
from relationship_query.infrastructure.graph_relation_queries import (
    DEFAULT_MODEL,
    GraphQueryModel,
    candidate_query,
    connected_query,
    evidence_query,
    qualified_query,
)
from relationship_query.infrastructure.source_graph_model import normalize_slot_proof
from relationship_query.services.ports import PathReader
from relationship_query.services.query import QueryError


class NativeGraphReader:
    def __init__(
        self,
        sql: PathReader,
        client: GraphClient,
        budget: PathBudget,
        month: int,
        model: GraphQueryModel = DEFAULT_MODEL,
    ) -> None:
        self.sql, self.client, self.budget, self.month = sql, client, budget, month
        self.model = model

    def persons(self, ids: list[str]) -> dict[str, Person]:
        return self.sql.persons(ids)

    def fact_views_by_ids(self, ids: list[str]) -> list[FactView]:
        return self.sql.fact_views_by_ids(ids)

    def paths(self, request: PathRequest) -> list[str]:
        candidates = self._candidates(request)
        if len(candidates) > request.limits.candidate_limit:
            self.budget.candidate_reasons.add("candidate_limit")
        candidates = candidates[: request.limits.candidate_limit]
        self.budget.graph_candidates = len(candidates)
        if not candidates:
            return []
        connected = self.client.execute(
            connected_query(request, self.month, candidates, self.model),
            self.budget,
            request.limits.path_limit + 1,
        )
        ids = [r["middle"] for r in connected]
        if len(set(ids)) != len(ids) or ids != sorted(ids) or not set(ids).issubset(candidates):
            raise QueryError("GRAPH_INTEGRITY", "图路径中间人物不一致", 503)
        if len(ids) > request.limits.path_limit:
            self.budget.candidate_reasons.add("path_limit")
        return ids[: request.limits.path_limit]

    def _candidates(self, request: PathRequest) -> list[str]:
        after = ""
        result: list[str] = []
        try:
            self._check_degree(request)
            while len(result) <= request.limits.candidate_limit:
                rows = self.client.execute(
                    candidate_query(request, self.month, after, model=self.model), self.budget, 129
                )
                page = [r["middle"] for r in rows]
                if not page:
                    break
                if page != sorted(set(page)) or page[0] <= after:
                    raise QueryError("GRAPH_INTEGRITY", "图候选分页顺序异常", 503)
                ids = page[:128]
                matched = self.client.execute(
                    qualified_query(request, self.month, ids, self.model), self.budget, len(ids)
                )
                matches = [r["middle"] for r in matched]
                if matches != sorted(set(matches)) or not set(matches).issubset(ids):
                    raise QueryError("GRAPH_INTEGRITY", "图候选核验结果异常", 503)
                result.extend(matches)
                if len(rows) <= 128:
                    break
                after = ids[-1]
        except PathBudgetExceeded as exc:
            if exc.reason != "graph_limit":
                raise
            self.budget.candidate_reasons.add("graph_limit")
        return result[: request.limits.candidate_limit + 1]

    def _check_degree(self, request: PathRequest) -> None:
        if self.model.source_slots:
            from relationship_query.infrastructure.graph_model import literal

            edges = self.model.edge_pattern(request.scope)
            rows = self.client.execute(
                f"MATCH (a)-[x:{edges}]->(e) WHERE id(a)=={literal(request.reference_id)} "
                "AND a.person.active AND x.active RETURN DISTINCT id(e) AS entity LIMIT 65",
                self.budget,
                65,
            )
            count = len(rows)
        else:
            person_vid = vid("p", request.reference_id)
            count = self.client.fetch("person", [person_vid], self.budget)[person_vid]["entities"]
        if count > 64:
            raise PathBudgetExceeded("graph_limit")

    def proofs(self, request: PathRequest, pairs: list[tuple[str, str]]) -> list[GraphProof]:
        if not 1 <= len(pairs) <= 10:
            raise ValueError("图证据批次必须为 1–10 段")
        rows = self.client.execute(
            evidence_query(request, self.month, pairs, self.model),
            self.budget,
            len(pairs) * (request.limits.evidence_limit + 1),
        )
        try:
            result = [
                GraphProof.model_validate(normalize_slot_proof(r) if self.model.source_slots else r)
                for r in rows
            ]
        except (ValidationError, ValueError, KeyError, TypeError):
            raise QueryError("GRAPH_INTEGRITY", "图证据格式异常", 503) from None
        if any((p.left_person, p.right_person) not in pairs for p in result):
            raise QueryError("GRAPH_INTEGRITY", "图证据端点异常", 503)
        for pair in pairs:
            keys = [
                (p.left_fact, p.right_fact)
                for p in result
                if (p.left_person, p.right_person) == pair
            ]
            if keys != sorted(set(keys)):
                raise QueryError("GRAPH_INTEGRITY", "图证据重复或顺序异常", 503)
        return result
