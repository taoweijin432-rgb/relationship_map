"""入口上下文跨同步工作线程传播，子预算不重启截止时间或图读取额度。"""

import logging
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import pytest

from relationship_query.domain.path_budget import (
    PathBudget,
    PathBudgetExceeded,
    relation_query_budget,
    shared_relation_budget,
)
from relationship_query.runtime.diagnostics import (
    DiagnosticTrace,
    capture,
    observe,
    request_id,
    stage,
    traced,
)


def test_children_share_graph_quota_and_keep_earliest_deadline():
    with shared_relation_budget() as parent:
        parent.deadline = monotonic() + 0.5
        first = PathBudget(10_000, 5000)
        assert abs(first.deadline - parent.deadline) < 0.01
        first.graph_request(19000)
        first.graph_result(19000)
        second = PathBudget(10_000, 5000)
        assert second.graph_rows == parent.graph_rows == 19000
        assert second.graph_calls == parent.graph_calls == 1
        with pytest.raises(PathBudgetExceeded, match="graph_limit"):
            second.graph_request(1001)
        assert parent.graph_calls == 1
        for _ in range(255):
            second.graph_request(0)
        with pytest.raises(PathBudgetExceeded, match="graph_limit"):
            first.graph_request(0)
    assert relation_query_budget().graph_rows == 0


def test_child_can_tighten_deadline_but_cannot_escape_cancel():
    with shared_relation_budget() as parent:
        child = PathBudget(50, 5000)
        assert child.deadline < parent.deadline
        parent.cancel()
        with pytest.raises(PathBudgetExceeded, match="cancelled"):
            child.check()
        assert child.progress() == 1 and child.interrupted == "cancelled"
    relation_query_budget().check()


def test_nested_sql_callbacks_count_against_entry_budget():
    with shared_relation_budget() as parent:
        parent.sql_limit = 3000
        first, second = PathBudget(5000, 100), PathBudget(5000, 100)
        assert first.progress() == 0
        assert second.progress() == 0
        assert second.progress() == 1
        assert parent.sql_steps == 3000 and second.interrupted == "sql_limit"


def test_diagnostic_nested_stages_and_failure_do_not_leak_context():
    trace = DiagnosticTrace(request_id="request-a")

    @traced("test.outer")
    def operation():
        assert request_id() == "request-a"
        with stage("test.inner"):
            observe("test.failure")
            raise ValueError("not logged")

    with capture(trace), pytest.raises(ValueError):
        operation()
    assert request_id() == "-"
    assert trace.observations == {"test.failure": 1}
    assert {key: value["calls"] for key, value in trace.totals().items()} == {
        "test.inner": 1,
        "test.outer": 1,
    }


def test_nested_capture_preserves_outer_benchmark_without_duplicate_counts():
    outer, inner = DiagnosticTrace(), DiagnosticTrace(request_id="request-inner")
    with capture(outer):
        with capture(inner, include_in_parent=True), stage("inner"):
            observe("work", 2)
            assert request_id() == "request-inner"
        with capture(outer), stage("outer"):
            observe("work")
    assert outer.observations == {"work": 3}
    assert set(outer.totals()) == {"inner", "outer"}
    assert inner.observations == {"work": 2}


def test_http_request_context_isolated_across_worker_threads(client, caplog, monkeypatch):
    query = client.app.state.query_service
    original = query.repository.suggest_people
    seen = []

    def read(keyword, limit):
        seen.append(request_id())
        observe("test.worker")
        assert relation_query_budget().deadline - monotonic() <= 5
        return original(keyword, limit)

    monkeypatch.setattr(query.repository, "suggest_people", read)
    with caplog.at_level(logging.INFO, logger="relationship_query"):
        with ThreadPoolExecutor(max_workers=3) as executor:
            responses = list(
                executor.map(
                    lambda _: client.get("/api/v1/persons/suggest?q=private-keyword"), range(3)
                )
            )
    assert all(response.status_code == 200 for response in responses)
    ids = {response.headers["X-Request-ID"] for response in responses}
    assert len(ids) == 3 and ids == set(seen)
    records = [
        r.getMessage() for r in caplog.records if "query request completed" in r.getMessage()
    ]
    assert len(records) == 3
    assert all(
        "test.worker" in message and "SQLRepository.suggest_people" in message
        for message in records
    )
    assert "private-keyword" not in caplog.text
    assert request_id() == "-"


def test_entry_budget_expiry_is_reported_with_request_id(client, monkeypatch, caplog):
    def expired(_keyword, _limit):
        observe("test.expired")
        relation_query_budget().deadline = monotonic() - 1
        return []

    monkeypatch.setattr(client.app.state.query_service.repository, "suggest_people", expired)
    with caplog.at_level(logging.INFO, logger="relationship_query"):
        response = client.get("/api/v1/persons/suggest")
    assert response.status_code == 503
    assert response.json()["code"] == "GRAPH_QUERY_LIMIT"
    assert response.headers["X-Request-ID"] in caplog.text
    assert "test.expired" in caplog.text and "error.time_limit" in caplog.text
    assert client.get("/api/v1/health").status_code == 200


def test_shared_usage_cannot_reset_graph_or_sql_quota():
    with shared_relation_budget() as caller:
        caller.graph_request(20)
        caller.graph_result(20)
        child = PathBudget(5000, 100, inherit_request=False)
        child.graph_request(19990)
        child.graph_result(19990)
        with pytest.raises(PathBudgetExceeded, match="graph_limit"):
            caller.absorb(child)
    with shared_relation_budget() as caller:
        caller.sql_steps = 200_000
        child = PathBudget(5000, 100, inherit_request=False)
        child.sql_steps = 350_000
        with pytest.raises(PathBudgetExceeded, match="sql_limit"):
            caller.absorb(child)
