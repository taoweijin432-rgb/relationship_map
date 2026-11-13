"""停服发布的文件级不变性、修正预检，以及显式本机 SQL／图集成。"""

import copy
import json
import os
import shlex
import socket
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.infrastructure import source_releases as releases
from relationship_query.infrastructure.handoff_trial import make_fixture
from relationship_query.infrastructure.projection_source_schema import MAPPING
from relationship_query.infrastructure.projection_source_trial import (
    make_projection_rows,
)
from relationship_query.infrastructure.source_corrections import (
    CorrectionPlan,
    corrected_snapshot,
    projection_difference,
)
from relationship_query.infrastructure.source_graph_model import SourceManifest
from relationship_query.infrastructure.source_read_model import source_digest
from relationship_query.services.query import QueryError

ROOT = Path(__file__).resolve().parents[2]


def raw_fixture():
    upstream, raw = make_fixture("a" * 64)
    return make_projection_rows(upstream, raw)[0]


def invalidation(data):
    rows = [dict(table="experts_work_experience", id=1)] + [
        dict(table=MAPPING, id=i) for i in (1001, 1002)
    ]
    return CorrectionPlan.model_validate(
        dict(
            base_digest=source_digest(data),
            at="2026-11-06T09:00:00",
            corrections=[
                {
                    **row,
                    "expected": {"deleted_at": None},
                    "values": {"deleted_at": "2026-11-06T09:00:00"},
                    "reason": "模拟上游失效",
                }
                for row in rows
            ],
        )
    )


def test_correction_is_copy_preserves_ids_and_removes_all_deleted_slots():
    before = raw_fixture()
    fingerprint = source_digest(before)
    after = corrected_snapshot(before, invalidation(before))
    difference = projection_difference(before, after)
    assert source_digest(before) == fingerprint and source_digest(after) != fingerprint
    assert [r["id"] for r in before[MAPPING]] == [r["id"] for r in after[MAPPING]]
    assert len(difference["removed_edges"]) == 2 and difference["added_edges"] == []
    assert difference["new_edge_count"] == difference["old_edge_count"] - 2
    assert {e["rank"] for e in difference["removed_edges"]} == {1001, 1002}


@pytest.mark.parametrize(
    "problem",
    [
        "wrong_base",
        "stale_expected",
        "missing_row",
        "missing_tombstone",
        "duplicate",
        "change_id",
        "unknown_table",
    ],
)
def test_correction_bad_input_does_not_change_input(problem):
    before = raw_fixture()
    fingerprint = source_digest(before)
    plan = invalidation(before).model_dump(mode="json")
    if problem == "wrong_base":
        plan["base_digest"] = "0" * 64
    elif problem == "stale_expected":
        plan["corrections"][0]["expected"]["deleted_at"] = "2026-01-01"
    elif problem == "missing_row":
        plan["corrections"][0]["id"] = 999999
    elif problem == "missing_tombstone":
        plan["corrections"].pop()
    elif problem == "duplicate":
        plan["corrections"].append(copy.deepcopy(plan["corrections"][0]))
    elif problem == "change_id":
        plan["corrections"][0]["values"] = {"id": 200}
    else:
        plan["corrections"][0]["table"] = "arbitrary_business_table"
    with pytest.raises(ValueError):
        corrected_snapshot(before, CorrectionPlan.model_validate(plan))
    assert source_digest(before) == fingerprint


def fake_bundle(path: Path, version: str) -> Path:
    path.mkdir()
    manifest = SourceManifest(
        space="relationship_lab_" + version,
        source_digest="a" * 64,
        source_database="relationship_lab_" + version,
        data_version=version,
        projection_id="graph-" + version,
        reference_month=202611,
        counts={},
    )
    (path / "manifest.json").write_text(manifest.model_dump_json())
    config = path / "api.env"
    config.touch(mode=0o600)
    config.write_text(
        "export RELATIONSHIP_SOURCE_API_MANIFEST="
        + shlex.quote(str(path / "manifest.json"))
        + "\nexport RELATIONSHIP_SOURCE_API_MYSQL_URL=mysql+pymysql://lab@127.0.0.1/relationship_lab_"
        + version
        + "\n"
    )
    credentials = path / "reader-credentials.json"
    credentials.touch(mode=0o600)
    credentials.write_text(json.dumps(dict(username="rq_aaaaaaaaaaaa", password="f" * 24)))
    return path


@pytest.fixture
def local_switch(monkeypatch, tmp_path):
    a, b = fake_bundle(tmp_path / "a", "a"), fake_bundle(tmp_path / "b", "b")
    monkeypatch.setattr(releases, "_stopped_services", nullcontext)
    monkeypatch.setattr(releases, "verify_bundle", releases.read_bundle)
    return tmp_path / "store", a, b


def test_atomic_activation_rollback_idempotence_and_pinned_version(local_switch):
    store, a, b = local_switch
    first = releases.activate(store, a)
    assert first.revision == 1 and first.previous is None
    pin = releases.load_active(store)
    pin.check()
    assert releases.activate(store, a) == first
    second = releases.activate(store, b)
    assert second.revision == 2 and second.previous == first.active
    with pytest.raises(QueryError) as error:
        pin.check()
    assert error.value.code == "RELEASE_CHANGED"
    third = releases.activate(store, rollback=True)
    assert third.revision == 3 and third.active == first.active
    assert [e.action for e in third.history] == ["activate", "activate", "rollback"]
    with pytest.raises(QueryError):
        pin.check()
    assert releases.load_active(store).bundle.directory == a
    assert (store / "active.json").stat().st_mode & 0o077 == 0
    assert not list(store.glob(".active-*.tmp"))


@pytest.mark.parametrize(
    "problem", ["missing_release", "verify_failure", "atomic_failure", "old_config_changed"]
)
def test_failed_publication_keeps_current_version(local_switch, monkeypatch, problem):
    store, a, b = local_switch
    releases.activate(store, a)
    if problem == "old_config_changed":
        releases.activate(store, b)
        (a / "manifest.json").write_text((a / "manifest.json").read_text() + "\n")
    before = (store / "active.json").read_bytes()
    if problem == "verify_failure":

        def fail(_directory):
            raise QueryError("GRAPH_VERSION_MISMATCH", "模拟混合批次", 409)

        monkeypatch.setattr(releases, "verify_bundle", fail)
    elif problem == "atomic_failure":

        def fail(*_args):
            raise OSError("模拟指针写入失败")

        monkeypatch.setattr(releases.os, "replace", fail)
    with pytest.raises((OSError, ValueError, QueryError)):
        releases.activate(
            store,
            None
            if problem == "old_config_changed"
            else (store / "missing" if problem == "missing_release" else b),
            rollback=problem == "old_config_changed",
        )
    assert (store / "active.json").read_bytes() == before
    assert not list(store.glob(".active-*.tmp"))


def test_pin_rejects_bundle_file_change(local_switch):
    store, a, _ = local_switch
    releases.activate(store, a)
    pin = releases.load_active(store)
    (a / "api.env").write_text((a / "api.env").read_text() + "\n")
    with pytest.raises(QueryError):
        pin.check()
    with pytest.raises(ValueError):
        releases.load_active(store)


def test_store_lock_rejects_parallel_switch(local_switch):
    store, a, _ = local_switch
    with releases._store_lock(store):
        with pytest.raises(RuntimeError, match="正在执行"):
            releases.activate(store, a)
    assert not (store / "active.json").exists()


def test_rollback_requires_a_retained_previous_release(local_switch):
    store, a, _ = local_switch
    with pytest.raises(ValueError, match="上一批次"):
        releases.activate(store, rollback=True)
    releases.activate(store, a)
    with pytest.raises(ValueError, match="上一批次"):
        releases.activate(store, rollback=True)


LIVE = pytest.mark.skipif(
    os.environ.get("RELATIONSHIP_SOURCE_RELEASE_TEST") != "1", reason="显式本机停服版本切换验收"
)


def live_paths():
    return Path(os.environ["RELATIONSHIP_RELEASE_A"]), Path(os.environ["RELATIONSHIP_RELEASE_B"])


@LIVE
def test_real_port_guard_refuses_running_service(tmp_path):
    a, _ = live_paths()
    store = tmp_path / "guard"
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 8000))
        listener.listen(1)
        with pytest.raises(RuntimeError, match="停止"):
            releases.activate(store, a)
    assert not (store / "active.json").exists()


@LIVE
def test_real_sql_graph_a_b_switch_stale_cursor_and_rollback(tmp_path):
    a, b = live_paths()
    store = tmp_path / "native-release"
    first = releases.activate(store, a)
    with TestClient(create_app(source_release_store=store)) as client:
        before = client.get("/api/v1/meta").json()
        assert before["data_version"] == first.active.data_version
        cursor = client.post("/api/v1/persons/search", json={"page_size": 2}).json()["next_cursor"]
        baseline = client.post(
            "/api/v1/relations/paths",
            json={
                "reference_id": "p:expert:1",
                "candidate_id": "p:resume:2",
                "scope": {"relation_type": "same_company_overlap"},
            },
        ).json()
        assert baseline["direct"]["evidence"][0]["overlap_months"] == 24
    second = releases.activate(store, b)
    assert second.active.data_version != first.active.data_version
    with TestClient(create_app(source_release_store=store)) as client:
        assert client.get("/api/v1/meta").json()["data_version"] == second.active.data_version
        stale = client.post("/api/v1/persons/search", json={"page_size": 2, "cursor": cursor})
        assert stale.status_code == 422 and stale.json()["code"] == "INVALID_CURSOR"
        facts = client.get("/api/v1/persons/p:expert:1/facts").json()["items"]
        assert [v["fact"]["id"] for v in facts] == ["slot:1003"] and facts[0]["entity"][
            "id"
        ] == "309"
        moved = client.get("/api/v1/persons/p:expert:5/facts").json()["items"]
        assert any(
            v["fact"]["id"] == "slot:1241"
            and v["fact"]["source_record_id"] == "experts_work_experience:19"
            for v in moved
        )
        proof = client.post(
            "/api/v1/relations/paths",
            json={
                "reference_id": "p:expert:1",
                "candidate_id": "p:resume:2",
                "scope": {"relation_type": "same_company_overlap"},
            },
        ).json()
        assert proof["direct"] is None and proof["paths"] == [] and proof["status"] == "not_found"
        company = client.get("/api/v1/entities/304").json()["entity"]
        assert (
            company["name"] == "模拟标准公司2（更名演练）" and "模拟标准公司2" in company["aliases"]
        )
        old_graph_paths = client.post(
            "/api/v1/relations/paths",
            json={
                "reference_id": "p:expert:1",
                "candidate_id": "p:resume:8",
                "scope": {"relation_type": "same_company_overlap"},
            },
        ).json()
        assert old_graph_paths["direct"] is None and old_graph_paths["paths"] == []
    third = releases.activate(store, rollback=True)
    assert third.active == first.active
    with TestClient(create_app(source_release_store=store)) as client:
        restored = client.get("/api/v1/meta").json()
        assert restored == before
        proof = client.post(
            "/api/v1/relations/paths",
            json={
                "reference_id": "p:expert:1",
                "candidate_id": "p:resume:2",
                "scope": {"relation_type": "same_company_overlap"},
            },
        ).json()
        assert proof["direct"] == baseline["direct"]
        assert (
            client.post(
                "/api/v1/persons/search", json={"page_size": 2, "cursor": cursor}
            ).status_code
            == 200
        )


@LIVE
def test_failed_mixed_sql_graph_does_not_replace_active(tmp_path):
    a, b = live_paths()
    store = tmp_path / "mixed-store"
    releases.activate(store, a)
    before = (store / "active.json").read_bytes()
    candidate = tmp_path / "mixed"
    candidate.mkdir()
    manifest = json.loads((a / "manifest.json").read_text())
    manifest["space"] = json.loads((b / "manifest.json").read_text())["space"]
    (candidate / "manifest.json").write_text(json.dumps(manifest))
    for name in ["api.env", "reader-credentials.json"]:
        target = candidate / name
        target.touch(mode=0o600)
        text = ((a if name == "api.env" else b) / name).read_text()
        if name == "api.env":
            text = text.replace(str(a / "manifest.json"), str(candidate / "manifest.json"))
        target.write_text(text)
    with pytest.raises(QueryError) as error:
        releases.activate(store, candidate)
    assert error.value.code == "GRAPH_VERSION_MISMATCH"
    assert (store / "active.json").read_bytes() == before
    assert (
        releases.load_active(store).bundle.manifest.data_version
        == releases.read_bundle(a).manifest.data_version
    )


@LIVE
def test_invalid_correction_blocks_before_new_database_or_query_bundle(tmp_path):
    import subprocess
    import sys

    a, _ = live_paths()
    plan = json.loads((ROOT / "docs/examples/source-correction-plan.json").read_text())
    plan["corrections"][-2]["values"]["entity_id"] = 999999
    file = tmp_path / "invalid-plan.json"
    file.write_text(json.dumps(plan))
    output = tmp_path / "must-not-exist"
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/source_corrections.py"),
            "--base",
            str(a),
            "--plan",
            str(file),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert process.returncode != 0 and "ENTITY_TYPE_OR_STATE" in process.stderr
    assert not output.exists()


@LIVE
def test_startup_failure_can_explicitly_rollback_to_retained_snapshot(tmp_path, monkeypatch):
    import importlib

    app_module = importlib.import_module("relationship_query.app")
    a, b = live_paths()
    store = tmp_path / "startup-failure"
    first = releases.activate(store, a)
    releases.activate(store, b)

    def unavailable(*_args, **_kwargs):
        raise QueryError("GRAPH_UNAVAILABLE", "模拟切换后启动依赖故障", 503)

    with monkeypatch.context() as patch:
        patch.setattr(app_module, "SourceGraphRepository", unavailable)
        with pytest.raises(QueryError):
            with TestClient(create_app(source_release_store=store)):
                pass
    assert (
        releases.read_state(store).active.data_version
        == releases.read_bundle(b).manifest.data_version
    )
    restored = releases.activate(store, rollback=True)
    assert restored.active == first.active
    with TestClient(create_app(source_release_store=store)) as client:
        assert client.get("/api/v1/health").status_code == 200


@LIVE
def test_running_api_rejects_out_of_band_activation_file_edit(tmp_path):
    a, _ = live_paths()
    store = tmp_path / "pin-guard"
    state = releases.activate(store, a)
    with TestClient(create_app(source_release_store=store)) as client:
        assert client.get("/api/v1/meta").status_code == 200
        # 仅改临时状态文件模拟绕过工具的操作，不改任何 SQL／图。
        (store / "active.json").write_text(
            state.model_copy(update={"revision": state.revision + 1}).model_dump_json()
        )
        response = client.get("/api/v1/meta")
        assert response.status_code == 409 and response.json()["code"] == "RELEASE_CHANGED"
