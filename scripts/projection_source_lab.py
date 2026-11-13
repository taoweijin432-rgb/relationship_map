"""六表归一输入、三表及原人物履历的隔离实验，不切换现有 API 图格式。"""

import argparse
import copy
import hashlib
import json
import re
import shlex
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from handoff_lab import create_lab
from sqlalchemy import MetaData, Table, insert, select, update
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from relationship_query.infrastructure.projection_source_graph import (
    project_graph,
    verify_business,
)
from relationship_query.infrastructure.projection_source_schema import (
    ENTITY,
    MAPPING,
    PREFIX,
    SLOTS,
    schema,
)
from relationship_query.infrastructure.projection_source_trial import (
    make_projection_rows,
    open_projection_engine,
    projection_records,
)

ROOT = Path(__file__).resolve().parents[1]


def serial(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=serial))


def checksum(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=serial).encode()
    ).hexdigest()


def raw_statements() -> list[str]:
    text = (ROOT / "docs/examples/expert-source-tables.sql").read_text()
    result = []
    for statement in text.split(";"):
        statement = re.sub(r"(?m)^--[^\n]*", "", statement).strip()
        if not statement:
            continue
        if not re.match(
            r"CREATE TABLE `experts(?:`|_(?:work|project|education)_experience`)",
            statement,
        ):
            raise ValueError("实验原表文件仅允许已核对的四条 CREATE TABLE")
        result.extend(
            [
                statement,
                statement.replace("experts", "resume").replace("expert", "resume"),
            ]
        )
    if len(result) != 8:
        raise ValueError("需要四张 Expert 及四张模拟 Resume 表")
    return result


def three_ddl() -> str:
    statements = []
    for table in schema.sorted_tables:
        statements.append(
            str(CreateTable(table).compile(dialect=mysql.dialect())).strip() + ";"
        )
        statements.extend(
            str(CreateIndex(i).compile(dialect=mysql.dialect())) + ";"
            for i in sorted(table.indexes, key=lambda i: i.name or "")
        )
    return (
        "-- 实验约束包含建议的槽位唯一键；缺失的合并／发布列未补造。\n\n"
        + "\n\n".join(statements)
        + "\n"
    )


def run(source: Path, document: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("输出必须为新目录，不覆盖历史实验")
    six_path, raw_path = (
        source / "source-snapshot.json",
        source / "synthetic-raw-experiences.json",
    )
    before_files = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (six_path, raw_path, document)
    }
    rows, bridge = make_projection_rows(
        json.loads(six_path.read_text()), json.loads(raw_path.read_text())
    )
    projection_records(rows)
    output.mkdir(parents=True, exist_ok=False)
    (output / "schema.sql").write_text(three_ddl())
    (output / "raw-schema.sql").write_text(";\n\n".join(raw_statements()) + ";\n")
    save(output / "bridge-ledger.json", bridge)
    url, version = create_lab()
    config = output / "source.env"
    config.touch(mode=0o600, exist_ok=False)
    config.write_text(
        "export RELATIONSHIP_PROJECTION_SOURCE_MYSQL_URL=" + shlex.quote(url) + "\n"
    )
    engine = open_projection_engine(url, writable=True)
    raw_schema = MetaData()
    try:
        with engine.connect() as connection:
            for statement in raw_statements():
                connection.exec_driver_sql(statement)
        schema.create_all(engine, checkfirst=False)
        for prefix in PREFIX.values():
            for name in (prefix, *[f"{prefix}_{suffix}" for suffix in SLOTS]):
                Table(name, raw_schema, autoload_with=engine)
        with engine.begin() as connection:
            for table in [*raw_schema.sorted_tables, *schema.sorted_tables]:
                connection.execute(insert(table), rows[table.name])
        tables = [*raw_schema.sorted_tables, *schema.sorted_tables]
        with engine.connect() as connection:
            snapshot = {
                t.name: [
                    dict(r)
                    for r in connection.execute(select(t).order_by(t.c.id)).mappings()
                ]
                for t in tables
            }
        nodes, edges = projection_records(snapshot)
        stability = stable_slot_rehearsal(engine, raw_schema, snapshot)
    finally:
        engine.dispose()
    reader = open_projection_engine(url)
    try:
        with reader.connect() as connection:
            after = {
                t.name: [
                    dict(r)
                    for r in connection.execute(select(t).order_by(t.c.id)).mappings()
                ]
                for t in tables
            }
    finally:
        reader.dispose()
    if checksum(snapshot) != checksum(after):
        raise ValueError("事务演练改动了源快照，不发布")
    save(output / "source-snapshot.json", snapshot)
    save(output / "nodes.json", nodes)
    save(output / "edges.json", edges)
    save(output / "slot-stability.json", stability)
    save(
        output / "resolution-trace.json",
        [
            {
                "mapping_id": m["id"],
                "source_table": m["source_table"],
                "source_field_id": m["source_field_id"],
                "source_field": m["source_field"],
                "entity_id": m["entity_id"],
                "matching_method": "upstream_uuid_bridge"
            if m["source_field"] in {"company_name", "school_name", "major"}
            and not m["source_table"].endswith("_project_experience")
                else "synthetic_governance_fixture",
            }
            for m in snapshot[MAPPING]
        ],
    )
    manifest = project_graph(nodes, edges, output / "graph", checksum(snapshot))
    business = verify_business(manifest, snapshot, output / "graph")
    if any(
        hashlib.sha256(Path(p).read_bytes()).hexdigest() != expected
        for p, expected in before_files.items()
    ):
        raise ValueError("输入文件在实验期间变化")
    report = {
        "data_mode": "mock",
        "status": "experimental_verified",
        "mysql_version": version,
        "database": engine.url.database,
        "input_sha256": before_files,
        "source_digest": checksum(snapshot),
        "input_unchanged": True,
        "source_unchanged": True,
        "counts": {name: len(items) for name, items in snapshot.items()},
        "bridge_entries": len(bridge),
        "stable_slot_checks": stability,
        "graph": manifest,
        "business_checks": business,
        "cloud_access": False,
        "api_projection_replaced": False,
        "warning": (
            "三表／真实形状原表／新 VID 与 Rank 独立验证；"
            "不是正式增量链路或现有 API 图格式迁移"
        ),
    }
    save(output / "report.json", report)
    save(output / "graph/lab-manifest.json", manifest)
    return report


def stable_slot_rehearsal(engine: Any, raw_schema: MetaData, snapshot: dict) -> dict:
    """在回滚事务中改目标／移归属／改名，不更新槽位主键。"""
    expected = next(
        m
        for m in snapshot[MAPPING]
        if m["source_system"] == "expert"
        and m["source_table"] == "experts_work_experience"
        and m["source_field_id"] == 1
        and m["source_field"] == "company_name"
    )
    other = next(
        m
        for m in snapshot[MAPPING]
        if m["source_system"] == "resume"
        and m["source_person_id"] == 8
        and m["edge_type"] == "worked_at"
    )
    target = next(e for e in snapshot[ENTITY] if e["id"] == other["entity_id"])
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                update(schema.tables[MAPPING])
                .where(
                    schema.tables[MAPPING].c.source_system == "expert",
                    schema.tables[MAPPING].c.source_table == "experts_work_experience",
                    schema.tables[MAPPING].c.source_field_id == 1,
                )
                .values(source_person_id=5)
            )
            connection.execute(
                update(schema.tables[MAPPING])
                .where(schema.tables[MAPPING].c.id == expected["id"])
                .values(entity_id=target["id"])
            )
            work = raw_schema.tables["experts_work_experience"]
            connection.execute(
                update(work)
                .where(work.c.id == 1)
                .values(expert_id=5, company_name=target["canonical_name"])
            )
            connection.execute(
                update(schema.tables[ENTITY])
                .where(schema.tables[ENTITY].c.id == target["id"])
                .values(canonical_name=target["canonical_name"] + "（模拟更名）")
            )
            changed = copy.deepcopy(snapshot)
            for table in (schema.tables[MAPPING], work, schema.tables[ENTITY]):
                changed[table.name] = [
                    dict(r) for r in connection.execute(select(table)).mappings()
                ]
            _, before = projection_records(snapshot)
            _, after = projection_records(changed)
            a = next(e for e in before if e["rank"] == expected["id"])
            b = next(e for e in after if e["rank"] == expected["id"])
            assert a["source"] != b["source"] and a["target"] != b["target"]
            assert b["source"] == "p:expert:5" and b["target"] == f"e:{target['id']}"
            return {
                "rank": expected["id"],
                "rank_unchanged": True,
                "owner_and_target_changed": True,
                "entity_rename_keeps_id": True,
                "rolled_back": True,
                "live_incremental_cleanup": False,
            }
        finally:
            transaction.rollback()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--six-source", type=Path, required=True)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.six_source, args.document, args.output)
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("status", "database", "counts", "graph", "warning")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
