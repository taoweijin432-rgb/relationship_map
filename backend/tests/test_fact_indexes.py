"""请求内跨会话事实复用；新请求、不同发布及失败读取均不误用旧记录。"""

import re
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from relationship_query.contracts import RelationScope
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.fixtures import make_dataset
from relationship_query.infrastructure.sql_paths import SQLPathReader
from relationship_query.infrastructure.sqlite import load_dataset, open_engine
from relationship_query.infrastructure.uuid_graph import (
    MaterializedGraphRepository,
    MaterializedReader,
    proof_batches,
    proof_query,
)
from relationship_query.runtime.fact_indexes import current_fact_indexes, fact_indexes
from relationship_query.services.query import QueryError


def budget():
    return PathBudget(5000, 5000)


def test_sql_facts_reused_across_readers_only_within_same_request(tmp_path):
    engine = open_engine(tmp_path / "facts.sqlite")
    data = make_dataset()
    load_dataset(engine, data)
    identity = next(f.id for f in data.facts if f.active)
    calls = []
    event.listen(engine, "before_cursor_execute", lambda *args: calls.append(1))
    try:
        with fact_indexes():
            first_budget, second_budget = budget(), budget()
            with engine.connect() as connection:
                first = SQLPathReader(connection, first_budget, data.reference_month)
                expected = first.fact_views_by_ids([identity, identity])
            assert first_budget.facts == 1
            calls.clear()
            with engine.connect() as connection:
                second = SQLPathReader(connection, second_budget, data.reference_month)
                assert second.fact_views_by_ids([identity]) == expected
            assert not calls and second_budget.facts == 0
            with engine.connect() as connection:
                different = SQLPathReader(connection, budget(), data.reference_month + 1)
                assert different.fact_views_by_ids([identity]) == expected
            assert len(calls) == 2
        assert current_fact_indexes() is None
        calls.clear()
        with fact_indexes(), engine.connect() as connection:
            assert (
                SQLPathReader(connection, budget(), data.reference_month).fact_views_by_ids(
                    [identity]
                )
                == expected
            )
        assert len(calls) == 2
    finally:
        engine.dispose()


def row(right_rank=2):
    return dict(
        left_person="p:expert:1",
        right_person=f"p:expert:{right_rank}",
        entity_vid="e:company:1",
        kind="same_company",
        left_rank=1,
        right_rank=right_rank,
    )


def graph_client():
    calls = []
    control = {"bad": False}

    def execute(statement, _budget, maximum):
        refs = re.findall(r'"(p:[^"]+)"->"(e:[^"]+)"@(\d+)', statement)
        calls.append(refs)
        assert len(refs) == maximum
        return [
            dict(
                source=person,
                target=entity,
                rank=int(rank) if not control["bad"] else 999,
                props=dict(
                    experience_key=f"expert:work:{rank}",
                    start_month=202001,
                    end_month=202212,
                    position_title="模拟岗位",
                    is_current=False,
                ),
            )
            for person, entity, rank in refs
        ]

    return (
        SimpleNamespace(execute=execute, manifest=SimpleNamespace(data_version="v1")),
        calls,
        control,
    )


def test_graph_fact_properties_reused_without_skipping_validation_or_poisoning_retry():
    client, calls, control = graph_client()
    with fact_indexes():
        first = MaterializedReader(None, client, budget())
        expected = first._facts([row()])
        assert len(calls) == 1 and len(calls[0]) == 2
        other = MaterializedReader(None, client, budget())
        assert other._facts([row()]) == expected and len(calls) == 1
        control["bad"] = True
        with pytest.raises(QueryError) as rejected:
            other._facts([row(3)])
        assert rejected.value.code == "GRAPH_INTEGRITY"
        control["bad"] = False
        assert len(other._facts([row(3)])) == 2
        assert len(calls[-1]) == 1
        client.manifest.data_version = "v2"
        assert MaterializedReader(None, client, budget())._facts([row()]) == expected
        assert len(calls[-1]) == 2
    assert current_fact_indexes() is None
    with fact_indexes():
        MaterializedReader(None, client, budget())._facts([row()])
    assert len(calls[-1]) == 2


def test_proof_batching_keeps_pair_limits_and_statement_size():
    pairs = [(f"p:expert:{i}", f"p:resume:{i}") for i in range(50)]
    scope = RelationScope(relation_type="same_company")
    small = list(proof_batches(scope, pairs, 2, budget()))
    assert [len(batch) for batch in small] == [64, 36]
    assert [branch for batch in small for branch in batch] == [
        (kind, *pair) for kind in ("same_company", "company_overlap") for pair in pairs
    ]
    large = list(proof_batches(scope, pairs, 1001, budget()))
    assert max(map(len, large)) == 8
    scoped = RelationScope(
        relation_type="same_company",
        relation_organization_ids=["company:" + str(i) + "x" * 90 for i in range(20)],
    )
    for batch in proof_batches(scoped, pairs, 21, budget()):
        statement = " UNION ALL ".join(
            proof_query(kind, scoped, left, right, 21) for kind, left, right in batch
        )
        assert len(statement.encode()) <= 48 * 1024
        assert statement.count("LIMIT 21") == len(batch)


def test_proof_batches_respect_remaining_rows_without_lowering_branch_limit():
    selected = budget()
    selected.graph_result(19950)
    batches = proof_batches(RelationScope(), [("p:expert:1", "p:expert:2")], 21, selected)
    assert len(next(batches)) == 2
    selected.graph_result(42)
    with pytest.raises(PathBudgetExceeded, match="graph_limit"):
        next(batches)


@pytest.mark.parametrize("invalid", ["wrong_kind", "wrong_pair", "too_many"])
def test_proof_count_validation_is_per_kind_and_pair(invalid):
    row = dict(
        kind="same_school",
        left_person="p:expert:1",
        right_person="p:expert:2",
        stored_source="p:expert:1",
        left_rank=1,
        right_rank=2,
    )
    if invalid == "wrong_kind":
        row["kind"] = "same_major"
    if invalid == "wrong_pair":
        row["right_person"] = "p:expert:3"
    rows = [row] * (3 if invalid == "too_many" else 1)
    client = SimpleNamespace(execute=lambda *args: rows)
    reader = MaterializedReader(None, client, budget())
    with pytest.raises(QueryError) as rejected:
        reader._relation_rows(
            RelationScope(relation_type="same_school"), [("p:expert:1", "p:expert:2")], 2
        )
    assert rejected.value.code == "GRAPH_INTEGRITY"


def test_nested_version_checks_merge_only_inside_same_work_and_keep_final_guard():
    calls = []

    @contextmanager
    def sql_session(selected):
        yield None

    graph = object.__new__(MaterializedGraphRepository)
    graph.client = SimpleNamespace(check_version=lambda selected: calls.append(selected))
    graph.source = SimpleNamespace()
    graph.sql = SimpleNamespace(session=sql_session)
    graph.cache = None
    selected = budget()
    with graph.candidate_session(selected):
        with graph.graph_session(selected):
            assert len(calls) == 1
    assert len(calls) == 2
    with graph.graph_session(selected):
        pass
    assert len(calls) == 4
    with pytest.raises(ValueError), graph.candidate_session(selected):
        raise ValueError("no leaked depth")
    with graph.candidate_session(selected):
        with graph.candidate_session(budget()):
            pass
    assert len(calls) == 9
