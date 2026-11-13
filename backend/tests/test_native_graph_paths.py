"""原生图关系引擎：禁止 SQL 路径计算，验证图内规则和来源装配。"""

import copy
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from relationship_query.app import create_app
from relationship_query.contracts import PathRequest
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.graph_client import GraphClient
from relationship_query.infrastructure.graph_relation_queries import candidate_query, evidence_query
from relationship_query.infrastructure.graph_relations import NativeGraphReader
from relationship_query.infrastructure.sql_paths import SQLPathReader
from relationship_query.services.query import QueryError
from tests.differential_data import differential_dataset
from tests.reference_oracle import scoped_proofs
from tests.test_graph_projection import golden_graph as golden_graph
from tests.test_graph_projection import published_fixture
from tests.test_paths import _expected_paths, _signatures

LIVE = pytest.mark.skipif(
    os.environ.get("RELATIONSHIP_GRAPH_TEST") != "1", reason="显式启用本机原生图路径验收"
)


def test_query_quotes_ids_and_preserves_window_source_rules():
    request = PathRequest(
        reference_id='人";RETURN 1',
        candidate_id="另一个",
        intermediate_source="expert",
        scope={
            "relation_type": "same_company_overlap",
            "relation_start_month": 202012,
            "relation_end_month": 202101,
            "min_overlap_months": 2,
        },
    )
    query = candidate_query(request, 202611)
    assert json.dumps('p|人";RETURN 1', ensure_ascii=False) in query
    assert "b.person.expert" in query and ">= 2" in query
    assert "202012" in query and "202101" in query and "202611" in query
    assert "SQL" not in query
    pairs = [("p:01", "p:02"), ("p:06", "p:07")]
    assert " UNION ALL " in evidence_query(request, 202611, pairs)


class CandidatePages:
    """只模拟图协议结果，独立检查跨页游标和资格过滤后的稳定前缀。"""

    def __init__(self, *, stop=False, invalid=False, entities=1):
        self.stop, self.invalid, self.entities = stop, invalid, entities
        self.statements = []

    def fetch(self, _tag, ids, _budget):
        return {ids[0]: {"entities": self.entities}}

    def execute(self, statement, _budget, _maximum):
        self.statements.append(statement)
        if "[member:affiliated]" in statement:
            if 'b.person.id > "m:0127"' in statement:
                if self.stop:
                    raise PathBudgetExceeded("graph_limit")
                ids = ["m:0128", "m:0129"]
            else:
                ids = [f"m:{i:04d}" for i in range(129)]
                if self.invalid:
                    ids[-1] = ids[0]
        else:
            ids = ["m:0128", "m:0129"] if "m:0129" in statement else ["m:0002", "m:0127"]
        return [{"middle": identity} for identity in ids]


@pytest.mark.parametrize("stop", [False, True])
def test_graph_candidate_pages_preserve_qualified_prefix_and_limits(stop):
    client = CandidatePages(stop=stop)
    budget = PathBudget(3000, 5000)
    reader = NativeGraphReader(None, client, budget, 202611)
    request = PathRequest(reference_id="a", candidate_id="b", limits={"candidate_limit": 3})
    assert reader._candidates(request) == (
        ["m:0002", "m:0127"] if stop else ["m:0002", "m:0127", "m:0128", "m:0129"]
    )
    assert ('b.person.id > "m:0127"') in client.statements[2]
    assert ("graph_limit" in budget.candidate_reasons) == stop


def test_graph_candidate_page_validates_lookahead_and_entity_budget():
    request = PathRequest(reference_id="a", candidate_id="b")
    reader = NativeGraphReader(None, CandidatePages(invalid=True), PathBudget(3000, 5000), 202611)
    with pytest.raises(QueryError, match="分页顺序"):
        reader._candidates(request)
    client, budget = CandidatePages(entities=65), PathBudget(3000, 5000)
    reader = NativeGraphReader(None, client, budget, 202611)
    assert reader._candidates(request) == []
    assert budget.candidate_reasons == {"graph_limit"} and not client.statements


@LIVE
@pytest.mark.parametrize("limit", [1, 2])
def test_native_evidence_prefix_sorting_matches_existing_contract(golden_graph, limit):
    path, manifest, _ = golden_graph
    request = {
        "reference_id": "p:01",
        "candidate_id": "p:02",
        "limits": {"evidence_limit": limit},
    }
    with TestClient(create_app(path)) as sql, TestClient(
        create_app(path, graph_manifest=manifest)
    ) as graph:
        a = sql.post("/api/v1/relations/paths", json=request)
        b = graph.post("/api/v1/relations/paths", json=request)
    assert a.status_code == b.status_code == 200
    assert a.json()["direct"] == b.json()["direct"]
    assert a.json()["paths"] == b.json()["paths"]


@LIVE
def test_graph_mode_does_not_run_sql_candidates_or_python_relationships(golden_graph, monkeypatch):
    import relationship_query.domain.rules as rules
    import relationship_query.services.paths as old

    def forbidden(*_args, **_kwargs):
        pytest.fail("原生图模式不能用 SQL／Python 重新计算关系路径")

    for name in ("candidates", "qualify_candidates", "_candidate_query", "fact_views"):
        monkeypatch.setattr(SQLPathReader, name, forbidden)
    monkeypatch.setattr(old, "build_evidence", forbidden)
    monkeypatch.setattr(rules, "overlap", forbidden)
    path, manifest, _ = golden_graph
    with TestClient(create_app(path, graph_manifest=manifest)) as client:
        statements = []
        engine = client.app.state.query_service.repository.engine

        def record(_c, _cu, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = client.post(
                "/api/v1/relations/paths",
                json={
                    "reference_id": "p:01",
                    "candidate_id": "p:07",
                    "scope": {"relation_type": "same_company_overlap"},
                },
            )
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert response.status_code == 200, response.text
        data = response.json()
    assert data["query_backend"] == "nebula" and data["paths"]
    fact_queries = [s for s in statements if "FROM demo_fact" in s]
    assert fact_queries and all("demo_fact.id IN" in s for s in fact_queries)
    assert all("EXISTS" not in s and "JOIN demo_fact" not in s for s in statements)
    assert data["stats"]["graph_candidates"] > 0


@LIVE
@pytest.mark.parametrize(
    "limits,reason",
    [
        ({"candidate_limit": 1}, "candidate_limit"),
        ({"fact_limit": 1}, "fact_limit"),
        ({"evidence_limit": 1}, "evidence_limit"),
    ],
)
def test_native_budgets_never_become_false_not_found(golden_graph, limits, reason):
    path, manifest, _ = golden_graph
    with TestClient(create_app(path, graph_manifest=manifest)) as client:
        response = client.post(
            "/api/v1/relations/paths",
            json={
                "reference_id": "p:01",
                "candidate_id": "p:02" if reason == "evidence_limit" else "p:07",
                "scope": {"relation_type": "same_company_overlap"}
                if reason != "evidence_limit"
                else {},
                "limits": limits,
            },
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["truncated"] and reason in data["truncation_reasons"]
    assert data["status"] != "not_found"


@LIVE
def test_graph_fact_drift_is_error_instead_of_silent_sql_recalculation(golden_graph, monkeypatch):
    original = GraphClient.execute

    def changed(self, statement, budget, maximum_rows):
        rows = original(self, statement, budget, maximum_rows)
        if rows and "left_properties" in rows[0]:
            rows = copy.deepcopy(rows)
            rows[0]["left_properties"]["start_month"] = 199901
        return rows

    monkeypatch.setattr(GraphClient, "execute", changed)
    path, manifest, _ = golden_graph
    with TestClient(create_app(path, graph_manifest=manifest)) as client:
        response = client.post(
            "/api/v1/relations/paths", json={"reference_id": "p:01", "candidate_id": "p:02"}
        )
    assert response.status_code == 503 and response.json()["code"] == "GRAPH_INTEGRITY"


@LIVE
def test_native_500_people_candidates_paths_and_evidence(tmp_path):
    raw = differential_dataset()
    scopes = [
        {},
        {"relation_type": "same_company"},
        {"relation_type": "same_school"},
        {"relation_type": "same_company_overlap"},
        {"relation_type": "same_company_overlap", "relation_start_month": 202012},
        {
            "relation_type": "same_company_overlap",
            "relation_end_month": 202101,
            "min_overlap_months": 2,
        },
    ]
    with published_fixture(tmp_path / "source.sqlite", tmp_path / "projection", raw) as (
        path,
        manifest,
        _,
    ):
        with TestClient(create_app(path, graph_manifest=manifest)) as client:
            for scope in scopes:
                for source in (None, "expert", "resume"):
                    request = {
                        "reference_id": "d:0001",
                        "candidate_id": "d:0023",
                        "scope": scope,
                        "intermediate_source": source,
                        "limits": {
                            "candidate_limit": 500,
                            "path_limit": 20,
                            "evidence_limit": 100,
                            "fact_limit": 5000,
                            "time_budget_ms": 3000,
                        },
                    }
                    response = client.post("/api/v1/relations/paths", json=request)
                    assert response.status_code == 200, response.text
                    data = response.json()
                    expected = _expected_paths(raw, "d:0001", "d:0023", scope, source)
                    assert [p["intermediate"]["id"] for p in data["paths"]] == [
                        p[0] for p in expected[:20]
                    ]
                    assert data["search_complete"] == (len(expected) <= 20)
                    for actual, (_, first, second) in zip(data["paths"], expected):
                        assert sorted(_signatures(actual["segments"][0])) == sorted(first)
                        assert sorted(_signatures(actual["segments"][1])) == sorted(second)
                    direct = sorted(_signatures(data["direct"])) if data["direct"] else []
                    assert direct == sorted(scoped_proofs(raw, "d:0001", "d:0023", scope))
