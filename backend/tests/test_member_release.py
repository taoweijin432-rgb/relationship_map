"""索引属于完整发布：启用后的构建、损坏拒绝、恢复及退出生命周期。"""

import json

import pytest
from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.infrastructure.member_index import build_member_index, index_binding
from relationship_query.infrastructure.real_api import RealGraphRepository
from relationship_query.services.query import QueryError
from relationship_query.update.models import GraphReceipt, Projection, UpdateError
from tests import test_nightly_release as nightly_tests
from tests import test_real_query as real_tests

real_release = real_tests.real_release
case = nightly_tests.case


def attach_index(directory):
    path = directory / "manifest.json"
    manifest = json.loads(path.read_text())
    binding = index_binding(
        directory,
        manifest["version"],
        manifest["source_digest"],
        manifest["reference_month"],
        GraphReceipt(**manifest["graph"]),
    )
    projection = Projection.model_validate_json((directory / "graph-plan.json").read_text())
    receipt = build_member_index(directory, projection, binding)
    manifest["query_index"] = receipt.model_dump(mode="json")
    path.write_text(json.dumps(manifest))
    return receipt


@pytest.mark.parametrize("policy", ["release", "nebula"])
def test_declared_index_is_validated_under_both_policies(real_release, monkeypatch, policy):
    before = RealGraphRepository(real_release)
    old_key = before.release_key
    before.engine.dispose()
    attach_index(real_release)
    monkeypatch.setenv("RELATIONSHIP_PLAN_ENGINE", policy)
    current = RealGraphRepository(real_release)
    try:
        assert current.member_index is not None
        assert current.plan_policy == policy and current.release_key != old_key
        path = real_release / "member-index/person-entities.u32"
        path.write_bytes(b"broken")
        with pytest.raises(QueryError) as error:
            current.verify_snapshot()
        assert error.value.code == "SOURCE_VERSION_MISMATCH"
    finally:
        current.close_query_index()
        current.engine.dispose()
    assert current.member_index.closed
    with pytest.raises(ValueError):
        RealGraphRepository(real_release)


def test_startup_failure_closes_mapping_after_index_loaded(real_release, monkeypatch):
    attach_index(real_release)
    mapped = []

    def failed_graph(source):
        mapped.append(source.member_index)
        assert not source.member_index.closed
        raise ValueError("injected graph startup failure")

    monkeypatch.setattr(RealGraphRepository, "graph_repository", failed_graph)
    with pytest.raises(ValueError, match="injected"):
        with TestClient(create_app(numeric_release_store=real_release)):
            pytest.fail("startup failed")
    assert mapped[0].closed


def test_enabling_index_rebuilds_same_source_and_missing_index_rolls_back(case):
    case.publisher.config = case.config.model_copy(update={"build_member_index": True})
    assert case.publisher.plan(case.previous)["status"] == "update_available"
    with pytest.raises(UpdateError) as error:
        case.publisher.run()
    assert error.value.code == "NIGHTLY_UPDATE_FAILED"
    assert case.config.environment_file.read_bytes() == case.original
    assert not case.config.maintenance_file.exists() and case.host.running


def test_indexed_candidate_publishes_and_committed_recovery_stays_forward(case, monkeypatch):
    case.publisher.config = case.config.model_copy(update={"build_member_index": True})

    def finish_index():
        attach_index(case.publisher._load().candidate)

    case.host.after_build = finish_index
    marker = case.publisher._marker

    def interrupted(operation, *, remove=False):
        if remove:
            raise KeyboardInterrupt()
        marker(operation)

    monkeypatch.setattr(case.publisher, "_marker", interrupted)
    with pytest.raises(KeyboardInterrupt):
        case.publisher.run()
    assert case.publisher._load().phase == "committed"
    monkeypatch.setattr(case.publisher, "_marker", marker)
    result = case.publisher.recover()
    assert result["status"] == "published"
    selected = case.publisher._load().candidate
    assert case.publisher.plan()["status"] == "up_to_date"
    source = RealGraphRepository(selected)
    assert source.member_index is not None
    source.close_query_index()
    source.engine.dispose()
    assert case.publisher.recover()["status"] == "idle"
