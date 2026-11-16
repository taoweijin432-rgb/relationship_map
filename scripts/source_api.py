"""从已验证的本地三表实验发布只读 API 配置；不写 SQL 或图，不接受云端来源。"""

import argparse
import json
import shlex
from pathlib import Path

from relationship_query.infrastructure.graph_model import read_reader
from relationship_query.infrastructure.projection_source_trial import (
    open_projection_engine,
    projection_records,
)
from relationship_query.infrastructure.source_api import (
    SourceGraphClient,
    SourceRepository,
)
from relationship_query.infrastructure.source_graph_model import SourceManifest
from relationship_query.infrastructure.source_publication import verify_graph


def source_url(path: Path) -> str:
    tokens = shlex.split(path.read_text())
    if (
        len(tokens) != 2
        or tokens[0] != "export"
        or not tokens[1].startswith("RELATIONSHIP_PROJECTION_SOURCE_MYSQL_URL=")
    ):
        raise ValueError("只接受本项目实验生成的单一来源配置，不执行 shell 内容")
    return tokens[1].split("=", 1)[1]


def run(source: Path, output: Path, reference_month: int) -> dict:
    if output.exists():
        raise FileExistsError("API 配置必须发布到新目录，不覆盖已有批次")
    report = json.loads((source / "report.json").read_text())
    if (
        report["status"] != "experimental_verified"
        or report["graph"]["format"] != "source-slot-lab-v2"
    ):
        raise ValueError("只接受已完整验证的三表本地实验")
    manifest = SourceManifest(
        source_database=report["database"],
        space=report["graph"]["space"],
        source_digest=report["source_digest"],
        projection_id="source-api-"
        + report["source_digest"][:20]
        + f"-{reference_month}",
        data_version="source-slots-v2-"
        + report["source_digest"][:20]
        + f"-{reference_month}",
        reference_month=reference_month,
        counts=report["counts"],
    )
    url = source_url(source / "source.env")
    engine = open_projection_engine(url)
    client = None
    try:
        repository = SourceRepository(engine, manifest)
        from relationship_query.infrastructure.source_read_model import snapshot

        with engine.connect() as connection:
            nodes, edges = projection_records(
                snapshot(connection, repository.source_schema)
            )
        client = SourceGraphClient(
            manifest, read_reader(source / "graph/lab-manifest.json")
        )
        verify_graph(client, nodes, edges)
        repository.verify_snapshot()
    finally:
        if client is not None:
            client.close()
        engine.dispose()
    output.mkdir(parents=True, exist_ok=False)
    credentials = output / "reader-credentials.json"
    credentials.touch(mode=0o600, exist_ok=False)
    credentials.write_bytes((source / "graph/reader-credentials.json").read_bytes())
    config = output / "api.env"
    config.touch(mode=0o600, exist_ok=False)
    config.write_text(
        "export RELATIONSHIP_SOURCE_API_MYSQL_URL=" + shlex.quote(url) + "\n"
        "export RELATIONSHIP_SOURCE_API_MANIFEST="
        + shlex.quote(str((output / "manifest.json").resolve()))
        + "\n"
    )
    # 清单最后落盘；失败目录不能作为已发布 API 配置使用。
    (output / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    return {
        "data_mode": "mock",
        "data_version": manifest.data_version,
        "nodes": len(nodes),
        "edges": len(edges),
        "source_unchanged": True,
        "graph_unchanged": True,
        "cloud_access": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-month", type=int, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.input, args.output, args.reference_month),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
