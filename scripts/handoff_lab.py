"""按核对后的六表定义新建本机 MySQL 实验源，转换为独立查询快照。"""

import argparse
import hashlib
import json
import os
import secrets
import shlex
from collections import Counter
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import create_engine, insert, select
from sqlalchemy.engine import Engine, make_url

from relationship_query.domain.validation import validate_payload
from relationship_query.infrastructure.handoff_checks import constraint_checks
from relationship_query.infrastructure.handoff_schema import ddl, schema
from relationship_query.infrastructure.handoff_trial import convert_tables, make_fixture
from relationship_query.infrastructure.mysql import open_mysql_engine
from relationship_query.infrastructure.sqlite import load_dataset, open_engine


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default)
    )


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    raise TypeError(type(value).__name__)


def read_tables(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    with engine.connect() as connection:
        return {
            table.name: [
                dict(r)
                for r in connection.execute(
                    select(table).order_by(table.c.id)
                ).mappings()
            ]
            for table in schema.sorted_tables
        }


def digest(rows: object) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=_json_default).encode()
    ).hexdigest()


def create_lab() -> tuple[str, str]:
    admin = make_url(
        os.environ.get(
            "RELATIONSHIP_MYSQL_ADMIN_URL", "mysql+pymysql://root@127.0.0.1:3306"
        )
    )
    if (
        admin.drivername != "mysql+pymysql"
        or admin.host not in {"127.0.0.1", "localhost"}
        or admin.database
        or admin.query
    ):
        raise ValueError("只允许本机 mysql+pymysql 管理连接，不指定数据库或附加参数")
    name = "relationship_lab_handoff_" + secrets.token_hex(6)
    engine = create_engine(
        admin, connect_args={"connect_timeout": 3}, hide_parameters=True
    )
    try:
        with engine.connect() as connection:
            version = str(connection.exec_driver_sql("SELECT VERSION()").scalar_one())
            numbers = tuple(int(n) for n in version.split("-")[0].split(".")[:3])
            if "MariaDB" in version or numbers < (8, 0, 16):
                raise ValueError("实验需要 MySQL 8.0.16 及以上的 CHECK 约束支持")
            connection.exec_driver_sql(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
            )
    finally:
        engine.dispose()
    return admin.set(database=name, query={"charset": "utf8mb4"}).render_as_string(
        hide_password=False
    ), version


def run(document: Path, output: Path) -> dict[str, Any]:
    if not document.is_file() or output.exists():
        raise ValueError("文档必须存在，输出必须为新目录；不覆盖已发布实验")
    started = perf_counter()
    document_digest = hashlib.sha256(document.read_bytes()).hexdigest()
    rows, raw = make_fixture(document_digest)
    convert_tables(rows, raw)
    output.mkdir(parents=True, exist_ok=False)
    (output / "schema.sql").write_text(ddl())
    write_json(output / "synthetic-raw-experiences.json", raw)
    url, version = create_lab()
    config = output / "source.env"
    config.touch(mode=0o600, exist_ok=False)
    config.write_text(
        "export RELATIONSHIP_HANDOFF_MYSQL_URL=" + shlex.quote(url) + "\n"
    )
    engine = open_mysql_engine(url, writable=True)
    try:
        schema.create_all(engine, checkfirst=False)
        with engine.begin() as connection:
            for table in schema.sorted_tables:
                connection.execute(insert(table), rows[table.name])
        before = read_tables(engine)
        checks = constraint_checks(engine, rows)
        if not all(c["rejected"] for c in checks):
            raise ValueError("MySQL 约束反例未全部被拒绝，不发布查询快照")
        if digest(before) != digest(read_tables(engine)):
            raise ValueError("反例探测改变了实验源数据，不发布")
    finally:
        engine.dispose()
    # 正常转换只通过只读连接取得数据库实际回读值，不绕过 MySQL 使用原 JSON。
    reader = open_mysql_engine(url)
    try:
        snapshot = read_tables(reader)
    finally:
        reader.dispose()
    dataset, trace, issues = convert_tables(snapshot, raw)
    _, validation = validate_payload(dataset.model_dump())
    write_json(output / "source-snapshot.json", snapshot)
    write_json(output / "dataset.json", dataset.model_dump())
    write_json(output / "provenance.json", trace)
    write_json(output / "issues.json", issues)
    write_json(output / "preflight.json", validation.model_dump())
    write_json(output / "constraint-checks.json", checks)
    target = open_engine(output / "query.sqlite")
    try:
        load_dataset(target, dataset)
    finally:
        target.dispose()
    if hashlib.sha256(document.read_bytes()).hexdigest() != document_digest:
        raise ValueError("参考文档在实验期间变化，不发布启动配置")
    report = {
        "data_mode": "mock",
        "status": "ready",
        "data_version": dataset.version,
        "document_sha256": document_digest,
        "mysql_version": version,
        "database": make_url(url).database,
        "table_counts": {k: len(v) for k, v in snapshot.items()},
        "source_digest": digest(snapshot),
        "source_unchanged_after_negative_tests": True,
        "cloud_access": False,
        "people": len(dataset.people),
        "facts": len(dataset.facts),
        "entities": len(dataset.entities),
        "slots": raw["slots"],
        "issues": dict(Counter(i["code"] for i in issues)),
        "constraints_passed": len(checks),
        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        "assumptions": [
            "批次 completed 仅为本轮就绪约定",
            "原人物履历和职位全部虚构",
            "未实现末尾边映射与稳定 Rank",
            "未定义的状态枚举和原表 DDL 仍待确认",
        ],
    }
    write_json(output / "report.json", report)
    config = output / ".env"
    config.touch(mode=0o600, exist_ok=False)
    config.write_text(
        "unset RELATIONSHIP_MYSQL_URL RELATIONSHIP_NEBULA_MANIFEST RELATIONSHIP_GRAPH_ENGINE\n"
        "export RELATIONSHIP_DATABASE="
        + shlex.quote(str((output / "query.sqlite").resolve()))
        + "\n"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.document, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
