"""新建轻量发布校验实验，复制冻结源或生成星形规模样例，全部写入新本机资源。"""

import argparse
import json
import secrets
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from handoff_lab import create_lab
from projection_source_lab import raw_statements, save
from relationship_query.infrastructure.graph_projection import (
    ProjectionWriter,
    _reader_account,
)
from relationship_query.infrastructure.mysql import lab_url
from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
)
from relationship_query.infrastructure.projection_source_schema import PREFIX
from relationship_query.infrastructure.projection_source_trial import (
    open_projection_engine,
)
from relationship_query.infrastructure.source_read_model import snapshot, source_digest
from relationship_query.infrastructure.source_releases import read_bundle
from relationship_query.infrastructure.sql_release_guard import install
from relationship_query.infrastructure.uuid_api import UUIDRepository
from relationship_query.infrastructure.uuid_projection import (
    calculate_relations,
    estimate,
    graph_digest,
    insert_edges,
    insert_nodes,
    meta_properties,
    read_all,
    schema_statements,
)
from relationship_query.infrastructure.uuid_source import (
    MODEL,
    NAMES,
    UUIDManifest,
    mock_schema,
    projection_records,
    reflect,
)
from relationship_query.infrastructure.uuid_verification import verify_bundle_graph
from sqlalchemy import insert

ROOT = Path(__file__).resolve().parents[1]


def scale_rows(size: int) -> dict:
    if not 1001 <= size <= 4000:
        raise ValueError("本轮星形样例人数范围为1001–4000名候选")
    rows = {name: [] for name in NAMES}

    def person(identity: int, source: str) -> dict:
        return dict(
            id=identity,
            serial_number=f"{source[0]}{identity:018d}",
            name=f"模拟规模人物{source}{identity}",
            interview_nickname="模拟",
            company="",
            job_name="",
            background="虚构规模验证",
            source_type=99,
        )

    rows["experts"] = [person(1, "expert")]
    rows["resume"] = [person(index + 2, "resume") for index in range(size)]
    for index in range(size):
        entity = str(uuid5(NAMESPACE_URL, f"relationship-query-scale-company-{index}"))
        rows["graph_company_entity"].append(
            dict(
                id=entity,
                standard_name=f"模拟规模公司{index:06d}",
                company_code=f"MOCK-{index:06d}",
                is_deleted=0,
            )
        )
        for source, owner in (("expert", 1), ("resume", index + 2)):
            table = PREFIX[source] + "_work_experience"
            raw_id = index + 1
            rows[table].append(
                dict(
                    id=raw_id,
                    **{f"{source}_id": owner},
                    company_name=f"模拟规模公司{index:06d}",
                    position_title="入选职位" if index % 17 == 0 else "其他职位",
                    start_date=datetime(2020, 1, 1),
                    end_date=datetime(2025, 12, 1),
                    is_employed=2,
                )
            )
            rows["graph_edge_mapping"].append(
                dict(
                    id=2 * index + (1 if source == "expert" else 2),
                    source_system=source,
                    source_table=table,
                    source_field_id=raw_id,
                    source_field="company_name",
                    source_person_id=owner,
                    standard_entity_id=entity,
                    edge_type="worked_at",
                )
            )
    return rows


def create_source(rows: dict) -> tuple[str, dict, str]:
    url, server = create_lab()
    engine = open_projection_engine(url, writable=True)
    try:
        with engine.connect() as connection:
            for ddl in raw_statements():
                connection.exec_driver_sql(ddl)
        mock_schema().create_all(engine, checkfirst=False)
        tables = reflect(engine)
        with engine.begin() as connection:
            for table in tables.sorted_tables:
                if rows[table.name]:
                    connection.execute(insert(table), rows[table.name])
        with engine.connect() as connection:
            frozen = snapshot(connection, tables, NAMES)
        return url, frozen, server
    finally:
        engine.dispose()


def build_graph(
    nodes: list[dict], facts: list[dict], manifest: UUIDManifest, output: Path
) -> tuple[UUIDManifest, list[dict]]:
    if estimate(facts) > 10000:
        raise ValueError("星形样例超出本轮构建预算")
    with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
        query(
            session,
            f"CREATE SPACE `{manifest.space}` "
            "(partition_num=1,replica_factor=1,vid_type=FIXED_STRING(128))",
        )
        query(session, f"USE `{manifest.space}`", wait=True)
        for ddl in schema_statements(ROOT):
            query(session, ddl, wait=True)
        writer = ProjectionWriter(session)
        meta = meta_properties(manifest, "staging")
        writer.vertices(
            "projection_meta", list(meta), [("meta:projection", list(meta.values()))]
        )
        insert_nodes(writer, nodes)
        insert_edges(writer, facts)
        relations = calculate_relations(session, nodes, manifest.reference_month)
        edges = facts + relations
        insert_edges(writer, relations)
        actual = read_all(lambda statement, maximum: query(session, statement), nodes)
        digest = graph_digest(nodes, edges)
        if graph_digest(*actual) != digest:
            raise ValueError("规模图完整回读不一致")
        credentials = _reader_account(session, output)
        query(
            session, f"GRANT ROLE GUEST ON `{manifest.space}` TO {credentials.username}"
        )
        manifest = manifest.model_copy(update={"graph_digest": digest})
        meta = meta_properties(manifest)
        writer.vertices(
            "projection_meta", list(meta), [("meta:projection", list(meta.values()))]
        )
    return manifest, edges


def reader_url(admin: str, manifest: UUIDManifest) -> str:
    engine = open_projection_engine(admin, writable=True)
    username, password = "rqsql_" + secrets.token_hex(6), secrets.token_hex(16)
    try:
        install(engine, manifest)
        with engine.connect() as connection:
            for host in ("localhost", "127.0.0.1"):
                connection.exec_driver_sql(
                    f"CREATE USER '{username}'@'{host}' IDENTIFIED BY %s", (password,)
                )
                connection.exec_driver_sql(
                    f"GRANT SELECT ON `{manifest.source_database}`.* TO '{username}'@'{host}'"
                )
    finally:
        engine.dispose()
    return (
        lab_url(admin)
        .set(username=username, password=password)
        .render_as_string(hide_password=False)
    )


def run(output: Path, source: Path | None, size: int | None) -> dict:
    if output.exists() or (source is None) == (size is None):
        raise ValueError("选择冻结来源或规模人数，输出目录须为新目录")
    prior = read_bundle(source) if source else None
    if prior:
        if not isinstance(prior.manifest, UUIDManifest):
            raise ValueError("只接受已发布 UUID 模拟快照")
        engine = open_projection_engine(prior.mysql_url)
        try:
            repository = UUIDRepository(engine, prior.manifest)
            with engine.connect() as connection:
                rows = snapshot(connection, repository.source_schema, NAMES)
        finally:
            engine.dispose()
    else:
        rows = scale_rows(size or 0)
    output.mkdir(parents=True, exist_ok=False)
    admin, frozen, server = create_source(rows)
    private = output / "admin.env"
    private.touch(mode=0o600)
    private.write_text(
        "export RELATIONSHIP_PROJECTION_SOURCE_MYSQL_URL=" + shlex.quote(admin) + "\n"
    )
    digest = source_digest(frozen)
    nodes, facts = projection_records(frozen, 202611)
    if prior:
        if digest != prior.manifest.source_digest:
            raise ValueError("复制的冻结 SQL 摘要不一致")
        manifest = UUIDManifest.model_validate(
            {
                **prior.manifest.model_dump(),
                "format_version": 4,
                "sql_guard": "mutation-sequence-v1",
                "source_database": lab_url(admin).database,
            }
        )
        shutil.copyfile(
            prior.directory / "reader-credentials.json",
            output / "reader-credentials.json",
        )
        (output / "reader-credentials.json").chmod(0o600)
        edges = json.loads((prior.directory / "graph-edges.json").read_text())
    else:
        version = f"uuid-v5-{digest[:20]}-202611"
        manifest = UUIDManifest(
            format_version=4,
            sql_guard="mutation-sequence-v1",
            source_database=lab_url(admin).database,
            space="relationship_lab_qscale_" + secrets.token_hex(6),
            projection_id=version,
            data_version=version,
            source_digest=digest,
            reference_month=202611,
            counts={name: len(items) for name, items in frozen.items()},
            graph_digest="0" * 64,
        )
        manifest, edges = build_graph(nodes, facts, manifest, output)
    reader = reader_url(admin, manifest)
    save(output / "source-snapshot.json", frozen)
    save(output / "graph-nodes.json", nodes)
    save(output / "graph-edges.json", edges)
    save(output / "manifest.json", manifest.model_dump(mode="json"))
    config = output / "api.env"
    config.touch(mode=0o600)
    config.write_text(
        "export RELATIONSHIP_SOURCE_API_MANIFEST="
        + shlex.quote(str((output / "manifest.json").resolve()))
        + "\nexport RELATIONSHIP_SOURCE_API_MYSQL_URL="
        + shlex.quote(reader)
        + "\n"
    )
    try:
        verify_bundle_graph(output)
    except Exception:
        (output / "manifest.json").unlink(missing_ok=True)
        raise
    report = dict(
        status="verified",
        model=MODEL,
        format_version=4,
        data_mode="mock",
        database=manifest.source_database,
        space=manifest.space,
        reference_person="p:expert:1",
        candidate_count=size,
        mysql_version=server,
        source_unchanged=bool(prior),
        cloud_access=False,
    )
    save(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", type=Path)
    parser.add_argument("--size", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.output, args.source_bundle, args.size),
            ensure_ascii=False,
            indent=2,
        )
    )
