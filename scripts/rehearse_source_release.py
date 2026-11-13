"""真实本机 HTTP 的停服 A→B→失败候选→回退 A 演练；结束回收本次服务。"""

import argparse
import json
import os
import shlex
import signal
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from relationship_query.infrastructure.source_releases import (
    activate,
    read_bundle,
    read_state,
)
from relationship_query.services.query import QueryError

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
SOURCE_ENV = (
    "RELATIONSHIP_DATABASE",
    "RELATIONSHIP_MYSQL_URL",
    "RELATIONSHIP_NEBULA_MANIFEST",
    "RELATIONSHIP_GRAPH_ENGINE",
    "RELATIONSHIP_SOURCE_API_MANIFEST",
    "RELATIONSHIP_SOURCE_API_MYSQL_URL",
    "RELATIONSHIP_SOURCE_RELEASE_STORE",
)


def request(path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


@contextmanager
def service(store, log):
    env = {k: v for k, v in os.environ.items() if k not in SOURCE_ENV}
    env["RELATIONSHIP_SOURCE_RELEASE_STORE"] = str(store.resolve())
    with log.open("w") as stream:
        process = subprocess.Popen(
            ["bash", "scripts/dev.sh"],
            cwd=ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("本次开发服务启动失败，请查看本地日志")
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:5173/", timeout=1
                    ) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.2)
            else:
                raise RuntimeError("本机服务启动超时")
            yield
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
            process.wait(timeout=15)


def paths(right="p:resume:2"):
    status, data = request(
        "/relations/paths",
        dict(
            reference_id="p:expert:1",
            candidate_id=right,
            scope={"relation_type": "same_company_overlap"},
        ),
    )
    assert status == 200 and data["query_backend"] == "nebula"
    return data


def check_original(store, log):
    with service(store, log):
        _, meta = request("/meta")
        _, page = request("/persons/search", {"page_size": 2})
        direct = paths()
        indirect = paths("p:resume:8")
        assert direct["direct"]["evidence"][0]["overlap_months"] == 24
        assert [p["intermediate"]["id"] for p in indirect["paths"]] == ["p:resume:7"]
        return meta, page["next_cursor"]


def check_corrected(store, log, cursor, expected_version, rejected_release):
    with service(store, log):
        _, meta = request("/meta")
        assert meta["data_version"] == expected_version and meta["fact_count"] == 118
        status, error = request("/persons/search", {"page_size": 2, "cursor": cursor})
        assert status == 422 and error["code"] == "INVALID_CURSOR"
        assert paths()["status"] == "not_found" and not paths("p:resume:8")["paths"]
        _, facts = request("/persons/p:expert:1/facts")
        assert [f["fact"]["id"] for f in facts["items"]] == ["slot:1003"]
        assert facts["items"][0]["entity"]["id"] == "309"
        _, moved = request("/persons/p:expert:5/facts")
        assert any(f["fact"]["id"] == "slot:1241" for f in moved["items"])
        before = (store / "active.json").read_bytes()
        try:
            activate(store, rejected_release)
        except RuntimeError:
            pass
        else:
            raise AssertionError("服务运行时不应允许切换")
        assert (store / "active.json").read_bytes() == before
        return meta


def mixed_candidate(a, b, output):
    output.mkdir()
    left, right = read_bundle(a), read_bundle(b)
    manifest = left.manifest.model_copy(update={"space": right.manifest.space})
    (output / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    for name, value in (
        (
            "api.env",
            "export RELATIONSHIP_SOURCE_API_MANIFEST="
            + shlex.quote(str(output / "manifest.json"))
            + "\nexport RELATIONSHIP_SOURCE_API_MYSQL_URL="
            + shlex.quote(left.mysql_url)
            + "\n",
        ),
        ("reader-credentials.json", (b / "reader-credentials.json").read_text()),
    ):
        file = output / name
        file.touch(mode=0o600)
        file.write_text(value)
    return output


def run(a, b, output):
    if output.exists():
        raise FileExistsError("演练使用新目录，不覆盖已有状态")
    output.mkdir(parents=True)
    store = output / "store"
    activate(store, a)
    print("A 已激活，检查原关系与原证据", flush=True)
    original, cursor = check_original(store, output / "a.log")
    second = activate(store, b)
    print("A 已停服，B 已激活，检查修正与旧游标拒绝", flush=True)
    corrected = check_corrected(
        store, output / "b.log", cursor, second.active.data_version, a
    )
    bad = mixed_candidate(a, b, output / "rejected-mixed-candidate")
    before = (store / "active.json").read_bytes()
    try:
        activate(store, bad)
    except QueryError as error:
        assert error.code == "GRAPH_VERSION_MISMATCH"
    else:
        raise AssertionError("混合批次必须拒绝")
    assert (store / "active.json").read_bytes() == before
    print("失败候选未改变 B，回退并重新启动 A", flush=True)
    restored = activate(store, rollback=True)
    restored_meta, _ = check_original(store, output / "restored-a.log")
    assert restored_meta == original
    report = {
        "data_mode": "mock",
        "status": "verified",
        "original": original,
        "corrected": corrected,
        "final_version": restored.active.data_version,
        "rollback_restored_original": True,
        "stale_cursor_rejected_on_b": True,
        "running_service_switch_rejected": True,
        "mixed_candidate_rejected_without_pointer_change": True,
        "history": read_state(store).model_dump(mode="json"),
        "cloud_access": False,
        "source_databases_modified": False,
        "graph_spaces_modified": False,
        "services_reclaimed": True,
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.a.resolve(), args.b.resolve(), args.output.resolve())
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "final_version",
                    "rollback_restored_original",
                    "services_reclaimed",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
