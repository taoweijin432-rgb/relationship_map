"""来源样例的只读转换、人工预期及三个实际运行模式。"""

import copy
import hashlib
import json
import os
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.infrastructure.source_trial import (
    build_mock_source,
    convert_source,
    inspect_seed,
    prepare_trial,
    read_seed,
)
from tests.reference_oracle import expected_people, scoped_proofs
from tests.test_paths import _expected_paths, _signatures

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "resources/examples/source-trial-sample.json"
CASES = json.loads((Path(__file__).parent / "fixtures/source-trial-cases.json").read_text())


def seed_source():
    return build_mock_source(read_seed(json.loads(INPUT.read_text())), "a" * 64)


def test_prepare_is_offline_reproducible_and_preserves_inputs(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("准备脚本不可访问网络")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    before = INPUT.read_bytes()
    first, second = tmp_path / "first", tmp_path / "second"
    a, b = prepare_trial(INPUT, first), prepare_trial(INPUT, second)
    assert a == b and a["data_mode"] == "mock"
    assert (first / "dataset.json").read_bytes() == (second / "dataset.json").read_bytes()
    assert INPUT.read_bytes() == before
    assert hashlib.sha256(before).hexdigest() == a["input_sha256"]
    existing = (first / "query.sqlite").read_bytes()
    with pytest.raises(FileExistsError):
        prepare_trial(INPUT, first)
    assert (first / "query.sqlite").read_bytes() == existing


@pytest.mark.parametrize("problem", ["duplicate", "target", "merged", "type", "root"])
def test_bad_seed_does_not_create_database(tmp_path, problem):
    raw = json.loads(INPUT.read_text())
    if problem == "duplicate":
        raw["company_standard"].append(raw["company_standard"][0])
    elif problem == "target":
        raw["name_mapping"][0]["company_id"] = "nonexistent"
    elif problem == "merged":
        row = next(r for r in raw["school_standard"] if r["verification_status"] == "已合并")
        row["merged_into_id"] = row["id"]
    elif problem == "type":
        raw["name_mapping"][0]["school_id"] = raw["school_standard"][0]["id"]
    else:
        raw = []
    file, out = tmp_path / "invalid.json", tmp_path / "not-published"
    file.write_text(json.dumps(raw))
    with pytest.raises((ValueError, KeyError)):
        prepare_trial(file, out)
    assert not out.exists()


def test_sample_issues_are_retained_and_do_not_create_real_ownership():
    seed = read_seed(json.loads(INPUT.read_text()))
    issues = inspect_seed(seed)
    assert {i["code"] for i in issues} >= {
        "MERGED_ENTITY",
        "UNCONFIRMED_MAPPING",
        "MISSING_ORIGINAL_KEY",
    }
    source = seed_source()
    dataset, trace = convert_source(source)
    assert len(dataset.people) == 60 and len(dataset.facts) == len(trace) == 122
    original_ids = {m.original_id for m in seed.mappings if m.original_id}
    assert all(f.source_record_id.startswith("mock-raw:") for f in dataset.facts)
    assert not original_ids.intersection(f.source_record_id for f in dataset.facts)
    assert all(p.name.startswith("模拟·") for p in dataset.people)
    assert {e.type for e in dataset.entities} == {"organization", "school", "role"}
    assert all(p["experience_is_synthetic"] for p in trace)
    assert all(p["mock_mapping_ids"] for p in trace)


def test_unused_upstream_columns_can_be_removed():
    payload = json.loads(INPUT.read_text())
    for kind in ("company", "school", "major"):
        for entity in payload[f"{kind}_standard"]:
            entity.pop("short_name", None)
            entity.pop("former_names", None)
            entity["new_processing_column"] = "无需程序使用"
    for mapping in payload["name_mapping"]:
        for field in (
            "source_file",
            "source_sheet",
            "source_row",
            "item_id",
            "item_no",
            "source_id",
            "source_namespace",
            "original_database_id",
        ):
            mapping.pop(field, None)
    seed = read_seed(payload)
    assert any(x["code"] == "MISSING_ORIGINAL_KEY" for x in inspect_seed(seed))
    dataset, _ = convert_source(build_mock_source(seed, "a" * 64))
    assert len(dataset.facts) == 122


def test_sampling_audit_contains_only_one_bounded_select():
    audit = json.loads((ROOT / "resources/data-sources/source-trial-cloud-read.json").read_text())
    assert audit["cloud_write_calls"] == audit["follow_up_cloud_calls"] == 0
    assert len(audit["calls"]) == 1
    call = audit["calls"][0]
    assert call["operation"] == "SELECT" and call["mapping_limit"] <= 100
    assert not call["views_called"] and not call["stored_procedures_called"]
    sql = (ROOT / "resources/examples/source-trial-sampling.sql").read_text().rstrip("\n")
    assert call["sql"] == sql


@pytest.mark.parametrize(
    "problem", ["missing", "split", "wrong_type", "owner", "date", "orphan", "real_id"]
)
def test_mock_source_rejects_unsafe_join(problem):
    source = seed_source()
    if problem == "missing":
        source.mappings = source.mappings[1:]
    elif problem == "split":
        source.mappings.append(
            source.mappings[0].model_copy(
                update={"id": "mock-map:split", "target_id": source.slots["org:1"]}
            )
        )
    elif problem == "wrong_type":
        source.mappings[0].target_id = source.slots["school:0"]
    elif problem == "owner":
        source.experiences[0].person_id = "unknown"
    elif problem == "date":
        source.experiences[0].end_month = 199901
    elif problem == "orphan":
        source.mappings[0].raw_id = "mock-raw:unknown"
    else:
        source.experiences[0].id = "real-original-record-id"
    with pytest.raises(ValueError):
        convert_source(source)


def test_duplicate_mock_mapping_preserves_trace_without_duplicate_facts():
    source = seed_source()
    source.mappings.append(source.mappings[0].model_copy(update={"id": "mock-map:duplicate"}))
    dataset, provenance = convert_source(source)
    assert len(dataset.facts) == 122
    assert provenance[0]["duplicate_mappings_collapsed"] == 1
    assert len(provenance[0]["mock_mapping_ids"]) == 2


def test_correction_only_changes_local_copy():
    source = seed_source()
    before = source.model_dump()
    dataset, _ = convert_source(source)
    corrected = copy.deepcopy(source)
    corrected.mappings[2].target_id = source.slots["org:1"]
    new, _ = convert_source(corrected)
    assert new.facts[2].entity_id != dataset.facts[2].entity_id
    assert source.model_dump() == before


@pytest.fixture(scope="module", params=["sqlite", "mysql", "nebula"])
def trial_client(request, tmp_path_factory):
    selected = os.environ.get("RELATIONSHIP_SOURCE_TRIAL_DIR")
    if request.param != "sqlite" and not selected:
        pytest.skip("实际三模式演练需显式指定本轮实验目录及匹配连接")
    directory = Path(selected) if selected else tmp_path_factory.mktemp("trial") / "run"
    if not selected:
        prepare_trial(INPUT, directory)
    kwargs = {}
    if request.param != "sqlite":
        assert os.environ.get("RELATIONSHIP_MYSQL_URL"), "需要本轮 MySQL 实验库"
        kwargs["mysql_url"] = os.environ["RELATIONSHIP_MYSQL_URL"]
    if request.param == "nebula":
        assert os.environ.get("RELATIONSHIP_NEBULA_MANIFEST"), "需要本轮图 manifest"
        kwargs["graph_manifest"] = Path(os.environ["RELATIONSHIP_NEBULA_MANIFEST"])
    raw = json.loads((directory / "dataset.json").read_text())
    slots = json.loads((directory / "report.json").read_text())["slots"]
    with TestClient(create_app(directory / "query.sqlite", **kwargs)) as client:
        assert client.get("/api/v1/meta").json()["data_version"] == raw["version"]
        yield client, raw, slots, request.param


def _filters(filters, slots):
    return {
        k: [slots.get(x, x) for x in v] if isinstance(v, list) else v for k, v in filters.items()
    }


def _all_pages(client, endpoint, filters):
    items, cursor = [], None
    for _ in range(100):
        response = client.post(endpoint, json={**filters, "page_size": 3, "cursor": cursor})
        assert response.status_code == 200, response.text
        data = response.json()
        items.extend(data["items"])
        if not data["has_more"]:
            return items
        cursor = data["next_cursor"]
        assert cursor
    pytest.fail("分页未结束")


@pytest.mark.parametrize("case", CASES["searches"], ids=lambda c: c["name"])
def test_trial_hand_checked_queries(trial_client, case):
    client, raw, slots, _ = trial_client
    filters = _filters(case["filters"], slots)
    items = _all_pages(client, "/api/v1/persons/search", filters)
    assert [i["person"]["id"] for i in items] == case["expected"]
    assert expected_people(raw, filters) == case["expected"]


@pytest.mark.parametrize("case", CASES["evidence"], ids=lambda c: c["name"])
def test_trial_hand_checked_evidence(trial_client, case):
    client, _, _, _ = trial_client
    response = client.get(
        "/api/v1/relations/evidence",
        params={"reference_id": case["left"], "candidate_id": case["right"]},
    )
    assert response.status_code == 200, response.text
    actual = sorted(
        (
            x["reference"]["fact"]["id"],
            x["candidate"]["fact"]["id"],
            x["overlap_start"],
            x["overlap_end"],
            x["overlap_months"],
        )
        for x in response.json()["items"]
        if x["relation_type"] == case["type"]
    )
    assert actual == sorted(tuple(p) for p in case["pairs"])


def test_trial_all_pages_relations_and_provenance(trial_client):
    client, raw, _, _ = trial_client
    items = _all_pages(client, "/api/v1/persons/search", {})
    assert [i["person"]["id"] for i in items] == [f"p:{i:06d}" for i in range(1, 61) if i != 11]
    assert [i["person"]["id"] for i in items].count("p:000013") == 1
    people = {i["person"]["id"]: i["person"] for i in items}
    assert people["p:000001"]["name"] == people["p:000012"]["name"]
    assert people["p:000013"]["sources"] == ["expert", "resume"]
    assert client.get("/api/v1/persons/p:000011/facts").status_code == 404
    for kind in ("same_company", "same_company_overlap", "same_school"):
        filters = {"relation_type": kind}
        related = _all_pages(client, "/api/v1/persons/p:000001/relations/search", filters)
        assert [i["person"]["id"] for i in related] == expected_people(raw, filters, "p:000001")
    for right in ("p:000002", "p:000003", "p:000004", "p:000005", "p:000008"):
        response = client.post(
            "/api/v1/persons/compare", json={"reference_id": "p:000001", "candidate_id": right}
        )
        assert response.status_code == 200
        evidence = client.get(
            "/api/v1/relations/evidence", params={"reference_id": "p:000001", "candidate_id": right}
        ).json()["items"]
        assert all(
            x[side]["fact"]["source_record_id"].startswith("mock-raw:")
            for x in evidence
            for side in ("reference", "candidate")
        )


@pytest.mark.parametrize(
    "scope", [{}, {"relation_type": "same_company_overlap"}, {"relation_type": "same_school"}]
)
def test_trial_paths_equal_independent_oracle(trial_client, scope):
    client, raw, _, mode = trial_client
    response = client.post(
        "/api/v1/relations/paths",
        json={
            "reference_id": "p:000001",
            "candidate_id": "p:000008",
            "scope": scope,
            "limits": {"path_limit": 20},
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["query_backend"] == ("nebula" if mode == "nebula" else "sql")
    assert result["search_complete"]
    expected = _expected_paths(raw, "p:000001", "p:000008", scope, None)
    assert [p["intermediate"]["id"] for p in result["paths"]] == [p[0] for p in expected]
    for actual, (_, first, second) in zip(result["paths"], expected):
        assert sorted(_signatures(actual["segments"][0])) == sorted(first)
        assert sorted(_signatures(actual["segments"][1])) == sorted(second)
    direct = sorted(_signatures(result["direct"])) if result["direct"] else []
    assert direct == sorted(scoped_proofs(raw, "p:000001", "p:000008", scope))
