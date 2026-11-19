"""成员计划的独立全图预期、工件损坏和资源／取消边界。"""

import json
import random
import struct
from collections import deque
from types import SimpleNamespace

import pytest

from relationship_query.contracts import RelationScope
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.member_index import (
    IndexBinding,
    MemberIndex,
    QueryIndexReceipt,
    build_member_index,
)
from relationship_query.infrastructure.member_traversal import (
    MemberPlanLimits,
    MemberTraversalView,
    supports_member_plan,
)
from relationship_query.services.query import QueryError
from relationship_query.update.artifacts import checksum
from relationship_query.update.models import GraphReceipt, Projection


def make_index(tmp_path, people, groups):
    facts = [
        dict(
            type=("worked_at", "studied_at", "studied_major")[i % 3],
            source=p,
            target=f"e:{('company', 'school', 'major')[i % 3]}:{i + 1}",
            rank=j + 1,
        )
        for i, group in enumerate(groups)
        for j, p in enumerate(group)
    ]
    projection = Projection(nodes=[dict(type="person", vid=p) for p in people], facts=facts)
    binding = IndexBinding(
        version="test",
        source_digest="a" * 64,
        reference_month=202611,
        graph=GraphReceipt(
            backend="test-double",
            space="test",
            graph_digest="b" * 64,
            node_count=len(people),
            fact_count=len(facts),
            relation_count=0,
        ),
        sql_sha256="c" * 64,
        graph_plan_sha256="d" * 64,
    )
    receipt = build_member_index(tmp_path, projection, binding)
    return receipt, binding


def oracle(people, groups, source, depth):
    # 以显式人物邻接表和标准FIFO BFS建立完整预期，不调用成员引擎或其排序函数。
    adjacency = {p: set() for p in people}
    for group in groups:
        for p in group:
            adjacency[p].update(set(group) - {p})
    found = {source: [source]}
    queue = deque([source])
    while queue:
        person = queue.popleft()
        if len(found[person]) > depth:
            continue
        for candidate in sorted(adjacency[person]):
            if candidate not in found:
                found[candidate] = found[person] + [candidate]
                queue.append(candidate)
    del found[source]
    return found


@pytest.mark.parametrize("seed", range(10))
def test_all_candidates_and_all_stable_chains_match_independent_bfs(tmp_path, seed):
    rng = random.Random(seed)
    people = [f"p:{'expert' if i % 2 else 'resume'}:{i}" for i in range(1, 31)]
    groups = [rng.sample(people[:27], rng.randint(1, 6)) for _ in range(22)]
    groups[0].extend(groups[0])  # 重复经历不产生重复归属。
    receipt, binding = make_index(tmp_path, people, groups)
    with MemberIndex(tmp_path, receipt, binding) as index:
        for source in (people[0], people[10], people[-1]):
            for depth in range(1, 5):
                view = MemberTraversalView(index, source, depth, PathBudget(5000, 5000))
                expected = oracle(people, groups, source, depth)
                assert view.block(None).ids == tuple(sorted(expected))
                assert view.chains(list(expected)) == expected
                view.close()
                with pytest.raises(RuntimeError):
                    view.block(None)
    assert index.closed and all(a.mapping is None for a in index.arrays)


def test_cross_128_blocks_string_order_and_prefix_tie_breaking(tmp_path):
    people = [f"p:expert:{i}" for i in range(1, 301)]
    groups = [[people[0], *people[1:150]], [people[1], *people[150:250]]]
    receipt, binding = make_index(tmp_path, people, groups)
    with MemberIndex(tmp_path, receipt, binding) as index:
        view = MemberTraversalView(index, people[0], 4, PathBudget(5000, 5000))
        first = view.block(None)
        assert len(first.ids) == 128 and first.has_more
        second = view.block(first.ids[-1])
        assert not second.has_more
        expected = oracle(people, groups, people[0], 4)
        assert first.ids + second.ids == tuple(sorted(expected))
        for page in (first.ids, second.ids):
            assert view.chains(list(page)) == {key: expected[key] for key in page}
        view.close()


def resign(directory, name):
    manifest_file = directory / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["files"][name].update(
        size=(directory / name).stat().st_size, sha256=checksum(directory / name)
    )
    manifest_file.write_text(json.dumps(manifest))
    return QueryIndexReceipt(manifest_sha256=checksum(manifest_file))


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "checksum",
        "offset",
        "value",
        "duplicate",
        "order",
        "reciprocal",
        "extra",
        "dictionary",
    ],
)
def test_bad_artifact_rejected_even_if_rehashed(tmp_path, damage):
    receipt, binding = make_index(
        tmp_path,
        [f"p:expert:{i}" for i in (1, 2, 3)],
        [["p:expert:1", "p:expert:2"], ["p:expert:3"]],
    )
    directory = tmp_path / "member-index"
    name = "entity-people.u32"
    path = directory / name
    if damage == "missing":
        path.unlink()
    elif damage == "extra":
        (directory / "extra").write_text("unlisted")
    elif damage == "checksum":
        path.write_bytes(b"bad")
    elif damage == "offset":
        name = "person-offsets.u64"
        path = directory / name
        path.write_bytes(struct.pack("<QQQQ", 0, 99, 1, 3))
    elif damage == "value":
        path.write_bytes(struct.pack("<III", 0, 1, 999))
    elif damage == "duplicate":
        path.write_bytes(struct.pack("<III", 0, 0, 2))
    elif damage == "order":
        path.write_bytes(struct.pack("<III", 1, 0, 2))
    elif damage == "reciprocal":
        path.write_bytes(struct.pack("<III", 0, 2, 1))
    else:
        name = "people.json"
        path = directory / name
        path.write_text('["private name"]')
    if damage not in ("missing", "extra", "checksum"):
        receipt = resign(directory, name)
    with pytest.raises((ValueError, OSError)):
        MemberIndex(tmp_path, receipt, binding)


def test_source_binding_size_and_little_endian_contract(tmp_path):
    receipt, binding = make_index(
        tmp_path, ["p:expert:1", "p:expert:2"], [["p:expert:1", "p:expert:2"]]
    )
    assert (tmp_path / "member-index/person-offsets.u64").read_bytes() == struct.pack(
        "<QQQ", 0, 1, 2
    )
    with pytest.raises(ValueError):
        MemberIndex(tmp_path, receipt, binding.model_copy(update={"version": "different"}))
    with pytest.raises(ValueError, match="容量"):
        MemberIndex(tmp_path, receipt, binding, maximum_bytes=1)


def test_workspace_scan_limit_and_cancellation_are_explicit(tmp_path):
    people = [f"p:expert:{i}" for i in range(1, 2000)]
    receipt, binding = make_index(tmp_path, people, [people])
    with MemberIndex(tmp_path, receipt, binding) as index:
        with pytest.raises(QueryError) as error:
            MemberTraversalView(
                index, people[0], 4, PathBudget(5000, 5000), MemberPlanLimits(workspace_bytes=1)
            )
        assert error.value.code == "GRAPH_QUERY_LIMIT"
        with pytest.raises(QueryError) as error:
            MemberTraversalView(
                index, people[0], 4, PathBudget(5000, 5000), MemberPlanLimits(member_scans=100)
            )
        assert error.value.reason == "budget.member_scans"

        class CancelOnCheckpoint(PathBudget):
            calls = 0

            def check(self):
                self.calls += 1
                if self.calls == 3:
                    self.cancel()
                super().check()

        selected = CancelOnCheckpoint(5000, 5000)
        with pytest.raises(PathBudgetExceeded, match="cancelled"):
            MemberTraversalView(index, people[0], 4, selected)
        assert selected.calls == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("relation_type", "same_company"),
        ("require_same_school", True),
        ("relation_organization_ids", ["company:1"]),
        ("relation_start_month", 202001),
        ("relation_end_month", 202212),
        ("min_overlap_months", 1),
    ],
)
def test_dynamic_scopes_never_use_static_plan(field, value):
    assert supports_member_plan(RelationScope())
    # 内部端口也逐字段拒绝，不能仅依赖HTTP模型对组合条件的校验。
    assert not supports_member_plan(RelationScope.model_construct(**{field: value}))


def test_execution_failure_never_changes_engine_and_nebula_policy_is_explicit(
    tmp_path, monkeypatch
):
    from relationship_query.domain.graph_relations import NeighborBlock
    from relationship_query.infrastructure import uuid_graph

    receipt, binding = make_index(
        tmp_path, ["p:expert:1", "p:expert:2"], [["p:expert:1", "p:expert:2"]]
    )
    with MemberIndex(tmp_path, receipt, binding) as index:
        graph = object.__new__(uuid_graph.MaterializedGraphRepository)
        graph.source = SimpleNamespace(member_index=index, plan_policy="release")
        graph.client = SimpleNamespace(check_version=lambda budget: None)
        calls = []

        def native(*args):
            calls.append(True)
            return NeighborBlock(ids=("p:expert:2",), has_more=False)

        graph.neighbor_block = native
        with graph.open_traversal("p:expert:1", RelationScope(), 4, PathBudget(5000, 5000)) as view:
            assert view.block(None).ids == ("p:expert:2",)
        assert not calls and view.closed
        for policy, scope in (
            ("nebula", RelationScope()),
            ("release", RelationScope(relation_type="same_company")),
        ):
            graph.source.plan_policy = policy
            with graph.open_traversal("p:expert:1", scope, 4, PathBudget(5000, 5000)) as view:
                assert view.block(None).ids == ("p:expert:2",)
        assert len(calls) == 2

        def failed(*args):
            raise QueryError("GRAPH_QUERY_LIMIT", "injected index work limit", 503)

        monkeypatch.setattr(uuid_graph, "MemberTraversalView", failed)
        with pytest.raises(QueryError):
            with graph.open_traversal("p:expert:1", RelationScope(), 4, PathBudget(5000, 5000)):
                pytest.fail("failed member engine returned a view")
        assert len(calls) == 2
