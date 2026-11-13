"""只读采集跨库图输入，人物及经历按权威映射引用范围读取。"""

import argparse
import getpass
import hashlib
import json
import os
import ssl
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Iterator, Literal

import pymysql  # type: ignore[import-untyped]

from relationship_query.infrastructure.mysql import TLSConnection
from relationship_query.update.artifacts import write_json
from relationship_query.update.mysql_source import json_row
from relationship_query.update.source_config import (
    MySQLReadEndpoint,
    MySQLSourceConfig,
    legacy_source_config,
)

ENTITY_TABLES = (
    "graph_company_entity",
    "graph_school_entity",
    "graph_major_entity",
    "graph_edge_mapping",
)
PERSON_TABLES = {
    "expert": ("experts", "experts_work_experience", "experts_education_experience"),
    "resume": ("resume", "resume_work_experience", "resume_education_experience"),
}
PERSON_FIELDS = (
    "id",
    "serial_number",
    "name",
    "city",
    "job_name",
    "deleted_at",
    "experts_id",
    "resume_id",
)
FACT_FIELDS = (
    "id",
    "expert_id",
    "resume_id",
    "start_date",
    "end_date",
    "company_name",
    "school_name",
    "major",
    "position_title",
    "is_employed",
    "education_level",
    "is_regular_enrollment",
    "deleted_at",
    "experience_id",
    "updated_at",
)


def connect_source(source: MySQLReadEndpoint, insecure_tls: bool) -> Any:
    context = ssl.create_default_context(cafile=source.tls_ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if insecure_tls:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if source.password_env is None:
        password = getpass.getpass(f"{source.host} {source.user} password: ")
    else:
        configured_password = os.environ.get(source.password_env)
        if not configured_password:
            raise ValueError(f"来源密码环境变量未设置或为空: {source.password_env}")
        password = configured_password
    for attempt in range(5):
        try:
            return TLSConnection(
                host=source.host,
                port=source.port,
                user=source.user,
                password=password,
                ssl=context,
                connect_timeout=8,
                read_timeout=30,
                write_timeout=8,
                cursorclass=pymysql.cursors.DictCursor,
            )
        except pymysql.OperationalError as error:
            if error.args[0] not in (2003, 2006, 2013) or attempt == 4:
                raise
            print(
                json.dumps(
                    {"host": source.host, "connection_retry": attempt + 1, "code": error.args[0]}
                ),
                flush=True,
            )
            sleep(2 * (attempt + 1))
    raise RuntimeError("来源连接重试未返回结果")


@contextmanager
def source_session(source: MySQLReadEndpoint, insecure_tls: bool) -> Iterator[Any]:
    with connect_source(source, insecure_tls) as connection:
        connection.select_db(source.database)
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION MAX_EXECUTION_TIME=10000")
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
        try:
            yield connection
        finally:
            connection.rollback()


def source_metadata(connection: Any, source: MySQLReadEndpoint, insecure_tls: bool) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT @@server_uuid AS server_uuid,VERSION() AS version,CURRENT_USER() AS account"
        )
        server = cursor.fetchone()
    return dict(
        host=source.host,
        port=source.port,
        database=source.database,
        server=server,
        captured_at=datetime.now(timezone.utc).isoformat(),
        certificate_verified=not insecure_tls,
        tls_version=connection._sock.version(),
        certificate_sha256=hashlib.sha256(
            connection._sock.getpeercert(binary_form=True)
        ).hexdigest(),
    )


def read_rows(
    connection: Any, table: str, columns: list[str] | None = None, ids: set[int] | None = None
) -> list[dict]:
    # 表列由固定白名单及information_schema限定，所有查询值均绑定参数。
    quoted = "`" + table.replace("`", "``") + "`"
    fields = "*" if columns is None else ",".join("`" + c.replace("`", "``") + "`" for c in columns)
    records: list[dict[str, Any]] = []
    with connection.cursor() as cursor:
        if ids is not None:
            ordered = sorted(ids)
            for offset in range(0, len(ordered), 200):
                batch = ordered[offset : offset + 200]
                placeholders = ",".join(["%s"] * len(batch))
                cursor.execute(
                    f"SELECT {fields} FROM {quoted} WHERE id IN ({placeholders}) ORDER BY id", batch
                )
                records.extend(json_row(row) for row in cursor.fetchall())
            return records
        after = None
        while True:
            where, parameters = ("", ()) if after is None else (" WHERE id>%s", (after,))
            cursor.execute(
                f"SELECT {fields} FROM {quoted}{where} ORDER BY id LIMIT 100", parameters
            )
            page = cursor.fetchall()
            if not page:
                return records
            records.extend(json_row(row) for row in page)
            after = page[-1]["id"]


def capture_entities(output: Path, source: MySQLReadEndpoint, insecure_tls: bool) -> dict:
    with source_session(source, insecure_tls) as connection:
        result: dict[str, Any] = {
            "metadata": source_metadata(connection, source, insecure_tls),
            "tables": {},
        }
        for table in ENTITY_TABLES:
            result["tables"][table] = read_rows(connection, table)
            print(json.dumps({"captured": table, "rows": len(result["tables"][table])}), flush=True)
        mappings = result["tables"]["graph_edge_mapping"]
        result["person_identity_audit"] = {}
        for source_system, (table, _, _) in PERSON_TABLES.items():
            ids = {
                row["source_person_id"] for row in mappings if row["source_system"] == source_system
            }
            result["person_identity_audit"][table] = read_rows(
                connection, table, ["id", "serial_number", "deleted_at"], ids
            )
    write_json(output / "entity-source.json", result)
    return result


def capture_people(
    output: Path,
    entities: dict,
    source: MySQLReadEndpoint,
    insecure_tls: bool,
    *,
    relation_only: bool = False,
) -> dict:
    mappings = entities["tables"]["graph_edge_mapping"]
    with source_session(source, insecure_tls) as connection:
        result: dict[str, Any] = {
            "metadata": source_metadata(connection, source, insecure_tls),
            "scope": "all-authoritative-mapping-references",
            "tables": {},
            "columns": {},
            "person_display": "mysql-live" if relation_only else "snapshot",
        }
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION",
                (source.database,),
            )
            for row in cursor.fetchall():
                result["columns"].setdefault(row["TABLE_NAME"], []).append(row["COLUMN_NAME"])
        for source_system, tables in PERSON_TABLES.items():
            selected = [
                row
                for row in mappings
                if row["source_system"] == source_system and row["deleted_at"] is None
            ]
            person, work, education = tables
            ids = {row["source_person_id"] for row in selected}
            fields = [field for field in PERSON_FIELDS if field in result["columns"][person]]
            if relation_only:
                fields = [field for field in fields if field not in {"name", "city", "job_name"}]
            result["tables"][person] = read_rows(connection, person, fields, ids)
            if relation_only:
                for row in result["tables"][person]:
                    # 旧投影契约要求非空name，此固定占位满足契约，实际展示由MySQL提供。
                    row.update(name="人物", city="", job_name="")
            for table in (work, education):
                ids = {row["source_field_id"] for row in selected if row["source_table"] == table}
                columns = [field for field in FACT_FIELDS if field in result["columns"][table]]
                result["tables"][table] = read_rows(connection, table, columns, ids)
            print(
                json.dumps(
                    {
                        "source": source_system,
                        "people": len(result["tables"][person]),
                        "work": len(result["tables"][work]),
                        "education": len(result["tables"][education]),
                    }
                ),
                flush=True,
            )
    write_json(output / "person-source.json", result)
    return result


def capture_sources(
    output: Path,
    config: MySQLSourceConfig,
    *,
    insecure_tls: bool = False,
    resume: bool = False,
    relation_only: bool = False,
) -> None:
    output.mkdir(mode=0o700, parents=True, exist_ok=resume)
    captured = {}
    files: dict[Literal["entities", "people"], str] = {
        "entities": "entity-source.json",
        "people": "person-source.json",
    }
    for role, name in files.items():
        path = output / name
        if not path.exists():
            continue
        result = json.loads(path.read_text())
        if role == "people" and relation_only != (result.get("person_display") == "mysql-live"):
            raise ValueError("续采输入的人物展示模式与本次配置不符")
        source = config.endpoint(role)
        metadata = result["metadata"]
        if (metadata["host"], metadata["port"], metadata["database"]) != (
            source.host,
            source.port,
            source.database,
        ):
            raise ValueError("已冻结来源与本次连接配置不符，请为新来源使用新目录")
        captured[role] = result
    entities = captured.get("entities")
    if entities is None:
        entities = capture_entities(output, config.endpoint("entities"), insecure_tls)
    if "people" not in captured:
        if relation_only:
            capture_people(
                output, entities, config.endpoint("people"), insecure_tls, relation_only=True
            )
        else:
            capture_people(output, entities, config.endpoint("people"), insecure_tls)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--person-database", help="沿用原测试连接")
    sources.add_argument("--source-config", type=Path, help="显式配置实体及人物的连接角色")
    parser.add_argument("--insecure-tls", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--relation-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    config = (
        MySQLSourceConfig.read(args.source_config)
        if args.source_config is not None
        else legacy_source_config(args.person_database)
    )
    capture_sources(
        output,
        config,
        insecure_tls=args.insecure_tls,
        resume=args.resume,
        relation_only=args.relation_only,
    )
    print(json.dumps({"captured": True, "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
