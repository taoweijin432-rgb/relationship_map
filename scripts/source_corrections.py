"""按明确模拟修正生成独立新 SQL／图快照，不更新原批次，不自动激活。"""

import argparse
import json
import shlex
from pathlib import Path

from handoff_lab import create_lab
from projection_source_lab import raw_statements, save, three_ddl
from relationship_query.infrastructure.projection_source_graph import project_graph
from relationship_query.infrastructure.projection_source_schema import schema
from relationship_query.infrastructure.projection_source_trial import (
    open_projection_engine,
    projection_records,
)
from relationship_query.infrastructure.source_api import SourceRepository
from relationship_query.infrastructure.source_corrections import (
    CorrectionPlan,
    corrected_snapshot,
    projection_difference,
)
from relationship_query.infrastructure.source_read_model import (
    reflect_source,
    snapshot,
    source_digest,
)
from relationship_query.infrastructure.source_releases import read_bundle, verify_bundle
from source_api import run as publish_api
from sqlalchemy import insert
from sqlalchemy.engine import make_url


def _clone_source(data: dict, output: Path) -> tuple[str, dict, str]:
    url, version = create_lab()
    config = output / "source.env"
    config.touch(mode=0o600, exist_ok=False)
    config.write_text(
        "export RELATIONSHIP_PROJECTION_SOURCE_MYSQL_URL=" + shlex.quote(url) + "\n"
    )
    engine = open_projection_engine(url, writable=True)
    try:
        with engine.connect() as connection:
            for statement in raw_statements():
                connection.exec_driver_sql(statement)
        schema.create_all(engine, checkfirst=False)
        tables = reflect_source(engine)
        with engine.begin() as connection:
            for table in tables.sorted_tables:
                if data[table.name]:
                    connection.execute(insert(table), data[table.name])
        with engine.connect() as connection:
            actual = snapshot(connection, tables)
        if source_digest(actual) != source_digest(data):
            raise ValueError("修正快照写入回读不一致，不发布")
        return url, actual, version
    finally:
        engine.dispose()


def run(base: Path, plan_file: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("修正批次必须使用新目录，不覆盖已有资源")
    plan_bytes = plan_file.read_bytes()
    plan = CorrectionPlan.model_validate_json(plan_bytes)
    bundle = verify_bundle(base)
    engine = open_projection_engine(bundle.mysql_url)
    try:
        source = SourceRepository(engine, bundle.manifest)
        with engine.connect() as connection:
            before = snapshot(connection, source.source_schema)
        changed = corrected_snapshot(before, plan)
        difference = projection_difference(before, changed)
        # 以上所有校验在新建库／目录之前完成，坏指令不产生半初始化查询库。
        output.mkdir(parents=True, exist_ok=False)
        (output / "schema.sql").write_text(three_ddl())
        (output / "raw-schema.sql").write_text(";\n\n".join(raw_statements()) + ";\n")
        url, actual, version = _clone_source(changed, output)
        nodes, edges = projection_records(actual)
        graph = project_graph(nodes, edges, output / "graph", source_digest(actual))
        source.verify_snapshot()
        if (
            read_bundle(base).digest != bundle.digest
            or plan_file.read_bytes() != plan_bytes
        ):
            raise ValueError("原批次配置或修正指令发生变化，不发布")
    finally:
        engine.dispose()
    report = {
        "status": "experimental_verified",
        "data_mode": "mock",
        "database": str(make_url(url).database),
        "mysql_version": version,
        "source_digest": source_digest(actual),
        "counts": {name: len(rows) for name, rows in actual.items()},
        "graph": graph,
        "base_data_version": bundle.manifest.data_version,
        "base_unchanged": True,
        "cloud_access": False,
        "warning": "本地完整重建，不是生产增量；模拟修正不证明上游规则",
    }
    save(output / "source-snapshot.json", actual)
    save(output / "correction-plan.json", plan.model_dump(mode="json"))
    save(output / "projection-difference.json", difference)
    save(output / "graph/lab-manifest.json", graph)
    save(output / "report.json", report)
    published = publish_api(output, output / "api", bundle.manifest.reference_month)
    save(output / "completion.json", published)
    return {**published, "base_unchanged": True, "activated": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(run(args.base, args.plan, args.output), ensure_ascii=False, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
