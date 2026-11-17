"""测量单位、稀疏文件和硬链接均不能放大或缩小资源结论。"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from relationship_query.benchmark.resources import directory_usage, peak_rss_bytes, process_usage
from relationship_query.benchmark.response_cost import response_usage


def test_rss_units_match_linux_and_darwin_kernel_contract():
    assert peak_rss_bytes(1234, "darwin") == 1234
    assert peak_rss_bytes(1234, "linux") == 1234 * 1024
    with pytest.raises(ValueError):
        peak_rss_bytes(1234, "unknown")
    result = process_usage()
    assert result["peak_rss_bytes"] > 0
    assert result["current_rss_bytes"] is None or result["current_rss_bytes"] > 0


def test_directory_counts_sparse_allocation_and_hard_links_without_following_links(tmp_path):
    directory = tmp_path / "owned"
    directory.mkdir()
    plain = directory / "plain"
    plain.write_bytes(b"hello")
    os.link(plain, directory / "hard-link")
    sparse = directory / "sparse"
    with sparse.open("wb") as stream:
        stream.truncate(16 * 1024 * 1024)
    (directory / "outside").symlink_to(tmp_path, target_is_directory=True)
    (directory / "file-link").symlink_to(plain)
    usage = directory_usage(directory)
    assert usage["regular_file_count"] == 3
    assert usage["logical_bytes"] == 10 + 16 * 1024 * 1024
    assert (
        usage["unique_file_allocated_bytes"]
        == (plain.stat().st_blocks + sparse.stat().st_blocks) * 512
    )
    assert usage["unique_file_allocated_bytes"] < usage["logical_bytes"]
    assert usage["skipped_links"] == 2


def test_response_duplicates_count_full_values_not_just_shared_identity():
    person = {"id": "p:1", "name": "测试", "sources": ["expert"], "headline": "研发"}
    fact = {"id": "f:1", "person_id": "p:1", "source_system": "expert", "entity_id": "c:1"}
    entity = {"id": "c:1", "type": "organization", "name": "甲公司", "aliases": []}
    body = json.dumps(
        [person, {"person": person, "fact": fact, "entity": entity}, {**person, "name": "更新"}],
        ensure_ascii=False,
    ).encode()
    usage = response_usage(body)
    assert usage["body_bytes"] == len(body)
    assert usage["objects"]["person"]["occurrences"] == 3
    assert usage["objects"]["person"]["unique_values"] == 2
    assert usage["objects"]["person"]["duplicate_canonical_bytes"] > 0
    assert usage["objects"]["fact"]["occurrences"] == 1
    assert usage["objects"]["entity"]["occurrences"] == 1
    assert usage["objects"]["entity"]["duplicate_canonical_bytes"] == 0
    assert "测试" not in json.dumps(usage, ensure_ascii=False)


@pytest.fixture
def lifecycle_profiler(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "lifecycle_profile", scripts / "profile_graph_lifecycle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("existing_graph", [False, True])
def test_lifecycle_profiler_never_cleans_unowned_or_existing_graph(
    tmp_path, monkeypatch, existing_graph, lifecycle_profiler
):
    module = lifecycle_profiler
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    if existing_graph:
        (candidate / "graph").mkdir()
        (candidate / ".resource-profile-owner.json").write_text(
            json.dumps({"format": "resource-profile-owned-v1", "token": "1" * 32})
        )
    else:
        (candidate / ".resource-profile-owner.json").write_text("{}")
    monkeypatch.setattr(module, "cleanup", lambda _: pytest.fail("拒绝候选不得触发清理"))
    with pytest.raises(ValueError):
        module.build(candidate, module.Recorder(tmp_path / "report.json", "build"))


def test_lifecycle_profiler_resolves_relative_candidate_before_real_build(
    tmp_path, monkeypatch, lifecycle_profiler
):
    import build_real_graph

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / ".resource-profile-owner.json").write_text(
        json.dumps({"format": "resource-profile-owned-v1", "token": "1" * 32})
    )
    observed = []

    def fake_build(path):
        assert path.is_absolute()
        observed.append(path)
        return {
            "version": "test",
            "graph": {"node_count": 0, "fact_count": 0, "relation_count": 0},
            "validation": {"passed": True},
        }

    monkeypatch.setattr(build_real_graph, "build", fake_build)
    monkeypatch.setattr(lifecycle_profiler, "cleanup", observed.append)
    monkeypatch.chdir(tmp_path)
    recorder = lifecycle_profiler.Recorder(tmp_path / "report.json", "build")
    lifecycle_profiler.build(Path("candidate"), recorder)
    assert observed == [candidate, candidate]
    assert recorder.data["resources_retired"] is True
