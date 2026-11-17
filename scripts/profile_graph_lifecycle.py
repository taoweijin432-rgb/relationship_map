"""在独立进程测量真实启动／准备／构建；不切发布，构建仅创建并清理本次实验资源。"""

import argparse
import gc
import json
import re
import signal
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from relationship_query.benchmark.resources import directory_usage, process_usage


class Recorder:
    def __init__(self, report: Path, action: str) -> None:
        if report.exists():
            raise FileExistsError("测量报告已存在，请使用独立路径")
        report.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path, self.started = report, perf_counter()
        self.data: dict[str, Any] = {"action": action, "passed": False, "samples": []}

    def sample(
        self, phase: str, directory: Path | None = None, **values: Any
    ) -> dict[str, Any]:
        row = {
            "phase": phase,
            "elapsed_ms": round((perf_counter() - self.started) * 1000, 3),
            **process_usage(),
            **values,
        }
        if directory is not None:
            row["directory"] = directory_usage(directory)
        self.data["samples"].append(row)
        self.save()
        return row

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
        self.path.chmod(0o600)


def startup(release: Path, recorder: Recorder) -> None:
    from fastapi.testclient import TestClient
    from relationship_query.app import create_app

    recorder.sample("after_import")
    app = create_app(numeric_release_store=release)
    recorder.sample("app_created")
    with TestClient(app) as client:
        recorder.sample("startup_complete")
        response = client.get("/api/v1/meta")
        response.raise_for_status()
        data = response.json()
        recorder.data["dataset"] = {
            key: data[key]
            for key in (
                "data_version",
                "reference_month",
                "person_count",
                "fact_count",
                "person_display",
            )
        }
        if any(app.state.admission.snapshot().values()):
            raise RuntimeError("启动测量后仍有在途任务")
    recorder.sample("closed")
    del app
    gc.collect()
    recorder.sample("references_released")


def prepare(source: Path, candidate: Path, month: int, recorder: Recorder) -> None:
    from build_real_graph import prepare as prepare_input

    recorder.sample("after_import")
    metadata = prepare_input(source, candidate, month)
    (candidate / ".resource-profile-owner.json").write_text(
        json.dumps(
            {
                "format": "resource-profile-owned-v1",
                "token": uuid4().hex,
            }
        )
    )
    (candidate / ".resource-profile-owner.json").chmod(0o600)
    recorder.data["dataset"] = {
        key: metadata[key]
        for key in ("version", "nodes", "facts", "relation_upper_bound")
    }
    recorder.sample("prepared", candidate)
    gc.collect()
    recorder.sample("references_released", candidate)


def cleanup(candidate: Path) -> None:
    from relationship_query.infrastructure.nebula_lab import (
        DEFAULT_CREDENTIALS,
        connect,
        load_credentials,
        query,
    )

    marker = candidate / "graph/build-resource.json"
    credentials = candidate / "graph/reader-credentials.json"
    space = json.loads(marker.read_text())["space"] if marker.exists() else None
    account = (
        json.loads(credentials.read_text())["username"]
        if credentials.exists()
        else None
    )
    if not space and not account:
        return
    if space and not re.fullmatch(r"relationship_lab_sync_[0-9a-f]{12}", space):
        raise ValueError("拒绝清理未知图空间")
    if account and not re.fullmatch(r"rq_[0-9a-f]{12}", account):
        raise ValueError("拒绝清理未知图账号")
    with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
        if space:
            query(session, f"DROP SPACE IF EXISTS `{space}`")
        if account:
            query(session, f"DROP USER IF EXISTS {account}")
        for statement, identity in (("SHOW SPACES", space), ("SHOW USERS", account)):
            if identity and any(
                identity in row.values() for row in query(session, statement)
            ):
                raise RuntimeError("本次实验资源尚未清理完成")


def build(candidate: Path, recorder: Recorder) -> None:
    import build_real_graph
    import relationship_query.infrastructure.uuid_projection as projection

    # 正式CLI同样先resolve；最终SQLite只读URI不能接受相对目录。
    candidate = candidate.resolve()
    owner = candidate / ".resource-profile-owner.json"
    if (candidate / "graph").exists() or not owner.is_file():
        raise ValueError("只接受本工具新准备且尚未建图的独立候选")
    ownership = json.loads(owner.read_text())
    if ownership.get("format") != "resource-profile-owned-v1" or not re.fullmatch(
        r"[0-9a-f]{32}", ownership.get("token", "")
    ):
        raise ValueError("候选所有权标记不符")
    recorder.sample("after_import", candidate)
    original = projection.stage

    @contextmanager
    def measured_stage(name: str) -> Iterator[None]:
        before = recorder.sample(name + ":before")
        started = perf_counter()
        with original(name):
            yield
        duration = (perf_counter() - started) * 1000
        after = recorder.sample(name + ":after", stage_ms=round(duration, 3))
        # 只有累计峰值刷新，才能将该新峰值明确归属这段区间；否则不虚构独占峰值。
        after["new_peak_during_stage"] = (
            after["peak_rss_bytes"] > before["peak_rss_bytes"]
        )
        recorder.save()

    projection.stage = measured_stage
    try:
        manifest = build_real_graph.build(candidate)
        recorder.data["dataset"] = {
            "version": manifest["version"],
            "node_count": manifest["graph"]["node_count"],
            "fact_count": manifest["graph"]["fact_count"],
            "relation_count": manifest["graph"]["relation_count"],
            "validation": manifest["validation"],
        }
        recorder.sample("built_and_verified", candidate)
    finally:
        projection.stage = original
        cleanup(candidate)
        recorder.data["resources_retired"] = True
        recorder.sample("resources_retired", candidate)


def interrupted(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("startup", "prepare", "build"))
    parser.add_argument("--release", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--reference-month", type=int, default=202611)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.candidate and args.report.resolve().is_relative_to(
        args.candidate.resolve()
    ):
        parser.error("报告须在候选目录之外，避免污染构建产物测量")
    recorder = Recorder(args.report, args.action)
    signal.signal(signal.SIGTERM, interrupted)
    recorder.sample("before_import")
    try:
        if args.action == "startup" and args.release:
            startup(args.release, recorder)
        elif args.action == "prepare" and args.input and args.candidate:
            prepare(args.input, args.candidate, args.reference_month, recorder)
        elif args.action == "build" and args.candidate:
            build(args.candidate, recorder)
        else:
            raise ValueError("启动需release，准备需input及candidate，构建需candidate")
        recorder.data["passed"] = True
    except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001 -- 独立测量进程终止边界
        # 摘要只输出失败类型；排障堆栈单独以私有权限保存，不进入控制台或版本库。
        recorder.data["error_type"] = type(error).__name__
        diagnostic = args.report.with_suffix(".traceback.txt")
        diagnostic.write_text(traceback.format_exc())
        diagnostic.chmod(0o600)
        recorder.data["private_traceback"] = str(diagnostic)
    finally:
        recorder.sample("process_finished")
    print(
        json.dumps(
            {
                key: value
                for key, value in recorder.data.items()
                if key not in {"samples", "dataset"}
            }
        )
    )
    return int(not recorder.data["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
