"""隔离MySQL最新版表、真实binlog、均衡虚构履历及原生图的端到端验证。"""

import argparse
import hashlib
import json
import secrets
import sqlite3
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from time import monotonic, perf_counter, sleep
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pymysql
from mysql_update_dataset import (
    MONTH,
    contract_for,
    distribution,
    expected_relations,
    make_dataset,
)
from projection_source_lab import raw_statements
from relationship_query.contracts import PathRequest
from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.graph_client import GraphClient
from relationship_query.infrastructure.graph_model import read_reader
from relationship_query.infrastructure.nebula_lab import DEFAULT_CREDENTIALS, query
from relationship_query.infrastructure.uuid_graph import MaterializedReader
from relationship_query.infrastructure.uuid_projection import read_all
from relationship_query.update.artifacts import artifact_directory, write_json
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import Cursor, UpdateError
from relationship_query.update.mysql_source import MySQLSource, json_row
from relationship_query.update.projection import NumericProjectionAdapter
from relationship_query.update.service import UpdateProgram
from relationship_query.update.store import UpdateStore
from relationship_query.update.target import NebulaTarget
from remote_mysql_lab import IMAGE, command
from update_program_lab import cleanup, reader_session

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "graph_sync_batch",
    "graph_company_entity",
    "graph_school_entity",
    "graph_major_entity",
    "graph_edge_mapping",
)


def start_mysql(output: Path, name: str) -> dict[str, Any]:
    password = secrets.token_hex(24)
    env = output / "container.env"
    env.touch(mode=0o600)
    env.write_text(f"MYSQL_ROOT_PASSWORD={password}\nMYSQL_ROOT_HOST=%\n")
    command(
        "docker",
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--cidfile",
        str(output / "container-id"),
        "--label",
        "relationship.test=latest-mysql-cdc",
        "--publish",
        "127.0.0.1::3306",
        "--env-file",
        str(env),
        IMAGE,
        "--server-id=183500",
        "--log-bin=binlog",
        "--binlog-format=ROW",
        "--binlog-row-image=FULL",
        "--binlog-row-metadata=FULL",
        "--gtid-mode=ON",
        "--enforce-gtid-consistency=ON",
    )
    settings = {
        "host": "127.0.0.1",
        "port": int(command("docker", "port", name, "3306/tcp").rsplit(":", 1)[1]),
        "user": "root",
        "password": password,
        "charset": "utf8mb4",
        "connect_timeout": 3,
        "read_timeout": 5,
        "write_timeout": 5,
    }
    deadline = monotonic() + 90
    while True:
        try:
            with closing(pymysql.connect(**settings)) as connection:
                connection.ping()
            return settings
        except pymysql.OperationalError:
            if monotonic() >= deadline:
                raise
            sleep(1)


def create_source(admin: dict, database: str, rows: dict) -> tuple[dict, dict]:
    settings = {**admin, "database": database}
    reader = {**settings, "user": "lab_cdc_reader", "password": secrets.token_hex(24)}
    with closing(pymysql.connect(**admin, autocommit=True)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"
            )
            cursor.execute(f"USE `{database}`")
            statements = (ROOT / "infra/mysql/schema/file-mapping-v1.sql").read_text()
            for statement in [*raw_statements(), *statements.split(";")]:
                if statement.strip():
                    cursor.execute(statement)
            cursor.execute(
                "CREATE USER 'lab_cdc_reader'@'%%' IDENTIFIED BY %s",
                (reader["password"],),
            )
            cursor.execute(f"GRANT SELECT ON `{database}`.* TO 'lab_cdc_reader'@'%'")
            cursor.execute(
                "GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO 'lab_cdc_reader'@'%'"
            )
        connection.begin()
        with connection.cursor() as cursor:
            order = [
                TABLES[0],
                *TABLES[1:4],
                "experts",
                "resume",
                "experts_work_experience",
                "resume_work_experience",
                "experts_education_experience",
                "resume_education_experience",
                "graph_edge_mapping",
            ]
            for table in order:
                records = rows[table]
                columns = list(records[0])
                cursor.executemany(
                    f"INSERT INTO `{table}` ("
                    + ",".join(f"`{column}`" for column in columns)
                    + ") VALUES ("
                    + ",".join(["%s"] * len(columns))
                    + ")",
                    [tuple(row[column] for column in columns) for row in records],
                )
        connection.commit()
    return settings, reader


def source_rows(settings: dict) -> dict[str, list[dict]]:
    result = {}
    with (
        closing(
            pymysql.connect(**settings, cursorclass=pymysql.cursors.DictCursor)
        ) as connection,
        connection.cursor() as cursor,
    ):
        for table in [
            *TABLES,
            "experts",
            "resume",
            "experts_work_experience",
            "resume_work_experience",
            "experts_education_experience",
            "resume_education_experience",
            "experts_project_experience",
            "resume_project_experience",
        ]:
            cursor.execute(f"SELECT * FROM `{table}` ORDER BY id")
            result[table] = [json_row(row) for row in cursor.fetchall()]
    return result


def check_schema(settings: dict, reader: dict) -> dict:
    expected = json.loads(
        (ROOT / "resources/data-sources/mysql-file-mapping-review-eafd2c32.json").read_text()
    )
    with (
        closing(
            pymysql.connect(**settings, cursorclass=pymysql.cursors.DictCursor)
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT VERSION() AS version")
        version = cursor.fetchone()["version"]
        cursor.execute(
            "SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION",
            (settings["database"],),
        )
        columns = defaultdict(list)
        for row in cursor.fetchall():
            columns[row["TABLE_NAME"]].append(row["COLUMN_NAME"])
    for table in TABLES:
        assert columns[table] == [
            field[0] for field in expected["mysql_table_fields"][table]
        ]
    assert len(columns) == 13 and sum(len(columns[table]) for table in TABLES) == 58
    with (
        closing(pymysql.connect(**reader)) as connection,
        connection.cursor() as cursor,
    ):
        try:
            cursor.execute("UPDATE graph_edge_mapping SET id=id WHERE id=-1")
        except pymysql.MySQLError as error:
            assert error.args[0] == 1142
        else:
            raise AssertionError("源采集账号意外拥有DML权限")
    return {
        "mysql_version": version,
        "tables": len(columns),
        "latest_columns": 58,
        "all_columns": sum(map(len, columns.values())),
        "source_write_denied": True,
    }


def relation_signature(row: dict) -> str:
    return json.dumps(
        {key: row[key] for key in ("source", "target", "type", "properties")},
        sort_keys=True,
        ensure_ascii=False,
    )


def verify_graph(
    path: Path, raw: dict, cases: list[dict], month: int, contract: SourceContract
) -> dict:
    manifest = json.loads(path.read_text())
    plan = json.loads((path.parent / "graph-plan.json").read_text())
    expected = expected_relations(raw, month)
    with reader_session(path) as session:
        query(session, f"USE `{manifest['graph']['space']}`")
        nodes, edges = read_all(
            lambda statement, maximum: query(session, statement), plan["nodes"]
        )
        all_two_hop = (
            verify_all_two_hop(session, expected, plan["nodes"]) if cases else {}
        )
    actual = [
        edge
        for edge in edges
        if edge["type"]
        in {"same_company", "company_overlap", "same_school", "same_major"}
    ]
    assert Counter(map(relation_signature, actual)) == Counter(
        map(relation_signature, expected)
    )
    verify_sql(path.parent / "source.sqlite", raw, contract, bool(cases))
    for node in nodes:
        if node["type"] == "person":
            assert set(node["properties"]) == {"serial_number", "source_system"}
    client = GraphClient(
        cast(Any, SimpleNamespace(space=manifest["graph"]["space"])), read_reader(path)
    )
    path_results = []
    for case in cases:
        direct = sorted(
            {
                edge["type"]
                for edge in actual
                if {edge["source"], edge["target"]} == {case["left"], case["right"]}
            }
        )
        assert direct == case["direct"], case
        request = PathRequest(reference_id=case["left"], candidate_id=case["right"])
        budget = PathBudget(3000, 5000)
        graph = MaterializedReader(cast(Any, None), cast(Any, client), budget)
        middle = sorted(graph.paths(request))
        assert middle == case["middle"], (case, middle)
        reverse = PathRequest(reference_id=case["right"], candidate_id=case["left"])
        reverse_reader = MaterializedReader(
            cast(Any, None), cast(Any, client), PathBudget(3000, 5000)
        )
        assert sorted(reverse_reader.paths(reverse)) == middle
        path_results.append({**case, "verified": True, "reverse_verified": True})
    if cases:
        verify_path_scopes(client, cases)
    return {
        "space": manifest["graph"]["space"],
        "to_seq": manifest["to_seq"],
        "month": month,
        "relation_evidence": dict(Counter(row["type"] for row in actual)),
        "path_cases": path_results,
        "sql_digest": manifest["source_digest"],
        "facts": len(edges) - len(actual),
        "person_names_absent": True,
        "local_sql_matches_cutoff": True,
        "all_two_hop": all_two_hop,
    }


def verify_all_two_hop(session: Any, relations: list[dict], nodes: list[dict]) -> dict:
    """全图按8个起点分块，独立邻接集合核对所有两跳三元组，含直接已关联的端点。"""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in relations:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    expected = {
        (left, middle, right)
        for left in adjacency
        for middle in adjacency[left]
        for right in adjacency[middle]
        if left < right and middle not in {left, right}
    }
    actual = set()
    people = [node["vid"] for node in nodes if node["type"] == "person"]
    pattern = "same_company|company_overlap|same_school|same_major"
    for offset in range(0, len(people), 8):
        anchors = json.dumps(people[offset : offset + 8])
        found = query(
            session,
            f"MATCH (a:person)-[x:{pattern}]-(m:person)-[y:{pattern}]-(b:person) "
            f"WHERE id(a) IN {anchors} AND id(a)<id(b) AND id(m)!=id(a) AND id(m)!=id(b) "
            "RETURN DISTINCT id(a) AS left_id,id(m) AS middle,id(b) AS right_id LIMIT 10001",
        )
        assert len(found) <= 10000
        actual.update((row["left_id"], row["middle"], row["right_id"]) for row in found)
    assert actual == expected, (len(actual), len(expected), list(actual ^ expected)[:5])
    pairs = {(left, right) for left, _, right in expected}
    two_only = {(left, right) for left, right in pairs if right not in adjacency[left]}
    assert len(two_only) > 100
    return {
        "middle_triples": len(expected),
        "endpoint_pairs": len(pairs),
        "two_hop_without_direct_pairs": len(two_only),
        "all_verified": True,
    }


def verify_sql(path: Path, raw: dict, contract: SourceContract, manual: bool) -> None:
    physical = {
        binding.physical: raw[binding.physical.split(".")[1]]
        for binding in contract.tables.values()
    }
    expected = contract.snapshot(physical)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        actual: dict[str, list[dict]] = defaultdict(list)
        for logical, payload in connection.execute(
            "SELECT logical_table,payload FROM source_row"
        ):
            actual[logical].append(json.loads(payload))
        for table in expected:
            assert sorted(actual[table], key=lambda row: row["id"]) == sorted(
                expected[table], key=lambda row: row["id"]
            ), table
        if not manual:
            return
        # 同一教育行的学校7＋专业8只匹配resume:9，expert:9的两行不能拼接。
        found = connection.execute("""
            WITH edges AS (
              SELECT json_extract(payload,'$.source_system') AS source,
                     json_extract(payload,'$.source_table') AS source_table,
                     json_extract(payload,'$.source_field_id') AS raw_id,
                     json_extract(payload,'$.source_person_id') AS person,
                     json_extract(payload,'$.edge_type') AS kind,
                     json_extract(payload,'$.standard_entity_id') AS target
              FROM source_row WHERE logical_table='edge_mapping'
            )
            SELECT DISTINCT s.source,s.person FROM edges s JOIN edges m
              ON s.source=m.source AND s.source_table=m.source_table AND s.raw_id=m.raw_id
            WHERE s.kind='studied_at' AND s.target=7 AND m.kind='studied_major' AND m.target=8
            """).fetchall()
        assert found == [("resume", 9)], found
        assert (
            connection.execute(
                "SELECT max(json_extract(payload,'$.id')) FROM source_row WHERE logical_table='edge_mapping'"
            ).fetchone()[0]
            == 9007199254740994
        )


def verify_path_scopes(client: GraphClient, cases: list[dict]) -> None:
    for index, case in enumerate(cases[:4]):
        request = PathRequest(
            reference_id=case["left"],
            candidate_id=case["right"],
            scope={"relation_type": "same_company_overlap"},
        )
        reader = MaterializedReader(
            cast(Any, None), cast(Any, client), PathBudget(3000, 5000)
        )
        assert sorted(reader.paths(request)) == (case["middle"] if index == 0 else [])
        expected_source = case["middle"][0].split(":")[1]
        request = PathRequest(
            reference_id=case["left"],
            candidate_id=case["right"],
            intermediate_source="resume" if expected_source == "expert" else "expert",
        )
        reader = MaterializedReader(
            cast(Any, None), cast(Any, client), PathBudget(3000, 5000)
        )
        assert reader.paths(request) == []


class SnapshotRaceSource(MySQLSource):
    def __init__(self, *args: Any, callback: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.callback = callback

    def _snapshot_rows(self, cursor: Any, limit: int) -> Any:
        self.callback()
        return super()._snapshot_rows(cursor, limit)


def verify_initial_handoff(
    settings: dict, reader: dict, contract: SourceContract
) -> dict:
    original = source_rows(settings)["experts"][0]["name"]
    changed = original + "（初始化并发校验）"

    def write_name(value: str) -> None:
        with (
            closing(pymysql.connect(**settings)) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("UPDATE experts SET name=%s WHERE id=1", (value,))
            connection.commit()

    probe = SnapshotRaceSource(
        reader,
        contract,
        "snapshot-race-probe",
        callback=lambda: write_name(changed),
        server_id=183502,
    )
    snapshot = probe.snapshot(settings)
    people = snapshot.tables[settings["database"] + ".experts"]
    assert next(row["name"] for row in people if row["id"] == 1) == original
    assert source_rows(settings)["experts"][0]["name"] == changed
    events = []
    for transaction in probe.transactions():
        events.extend(transaction.events)
        probe.acknowledge(transaction)
    assert (
        len(events) == 1
        and events[0].before["name"] == original
        and events[0].after["name"] == changed
    )
    write_name(original)
    return {"snapshot_kept_old_row": True, "cdc_delivered_concurrent_commit": True}


def mutate_during_build(
    settings: dict, program: UpdateProgram, source: MySQLSource
) -> list[dict]:
    states = []
    with closing(
        pymysql.connect(**settings, cursorclass=pymysql.cursors.DictCursor)
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM graph_edge_mapping WHERE source_system='expert' AND source_person_id=1 AND standard_entity_id=1 AND edge_type='worked_at'"
            )
            edge = cursor.fetchone()
            cursor.execute("SELECT standard_name FROM graph_company_entity WHERE id=2")
            target_name = cursor.fetchone()["standard_name"]
            cursor.execute(
                "UPDATE experts_work_experience SET company_name=%s,position_title=%s WHERE id=%s",
                (target_name, "研发项目负责人", edge["source_field_id"]),
            )
            cursor.execute(
                "UPDATE graph_edge_mapping SET standard_entity_id=2,updated_at=UTC_TIMESTAMP(6) WHERE id=%s",
                (edge["id"],),
            )
        connection.commit()
        states.append(source_rows(settings))
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM graph_edge_mapping WHERE source_system='expert' AND source_person_id=9 AND edge_type='studied_at' ORDER BY id LIMIT 1"
            )
            removed = cursor.fetchone()
            cursor.execute(
                "DELETE FROM graph_edge_mapping WHERE id=%s", (removed["id"],)
            )
        connection.commit()
        states.append(source_rows(settings))
    captured = program.capture(source)
    assert captured == {"captured": 2, "replayed": 0}, captured
    return [*states, removed]


class CapturingTarget:
    def __init__(self, target: NebulaTarget, callback: Any) -> None:
        self.target, self.callback, self.states = target, callback, []

    def build_and_verify(self, projection: Any, context: Any) -> Any:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.callback)
            receipt = self.target.build_and_verify(projection, context)
            self.states = future.result(timeout=30)
            return receipt


def export_sql(name: str, database: str, output: Path) -> None:
    result = subprocess.run(
        [
            "docker",
            "exec",
            name,
            "sh",
            "-c",
            (
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --set-gtid-purged=OFF '
                f"--no-tablespaces --databases {database}"
            ),
        ],
        check=True,
        capture_output=True,
    )
    (output / "source-final.sql").write_bytes(result.stdout)


def run(output: Path, credentials: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    name, database = (
        "relationship-latest-" + uuid4().hex[:10],
        "relationship_lab_latest_" + uuid4().hex[:12],
    )
    report: dict[str, Any] = {
        "mode": "fictional-native-mysql-binlog-and-nebula",
        "dataset_version": "fictional-balanced-careers-v2",
        "passed": False,
        "stages": [],
    }
    report["code_sha256"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [
            Path(__file__),
            ROOT / "scripts/mysql_update_dataset.py",
            ROOT / "backend/src/relationship_query/update/mysql_source.py",
            ROOT / "backend/src/relationship_query/update/projection.py",
            ROOT / "infra/mysql/schema/file-mapping-v1.sql",
        ]
    }
    started_container = False
    try:
        admin = start_mysql(output, name)
        started_container = True
        rows, cases, profiles = make_dataset()
        settings, reader = create_source(admin, database, rows)
        report.update(check_schema(settings, reader))
        report["distribution"] = distribution(rows, expected_relations(rows))
        write_json(output / "fictional-careers.json", profiles)
        write_json(output / "manual-cases.json", cases)
        contract = SourceContract.model_validate(contract_for(database))
        write_json(output / "contract.json", contract.model_dump(mode="json"))
        report["initial_handoff"] = verify_initial_handoff(settings, reader, contract)
        source = MySQLSource(reader, contract, "latest-lab-" + uuid4().hex[:12])
        snapshot = source.snapshot(settings)
        write_json(output / "baseline.json", snapshot.model_dump(mode="json"))
        baseline = source_rows(settings)
        store = UpdateStore(output / "state", contract, create=True)
        program = UpdateProgram(store, NumericProjectionAdapter(contract))
        program.bootstrap(snapshot, MONTH)
        target = NebulaTarget(credentials)
        capturing = CapturingTarget(
            target, lambda: mutate_during_build(settings, program, source)
        )
        baseline_path = None
        for stage in range(5):
            if stage == 3:
                restore_and_delete(settings, capturing.states[2])
                assert program.capture(source) == {"captured": 1, "replayed": 0}
            month = MONTH if stage < 4 else 202612
            gold = (
                baseline
                if stage == 0
                else capturing.states[stage - 1]
                if stage < 3
                else source_rows(settings)
            )
            started = perf_counter()
            manifest = program.process(
                month, capturing if stage == 0 else target, max_transactions=1
            )
            assert manifest is not None and manifest.to_seq == min(stage, 3)
            path = (
                artifact_directory(store.directory, manifest.batch_id, manifest.token)
                / "manifest.json"
            )
            result = verify_graph(
                path, gold, cases if stage == 0 else [], month, contract
            )
            result["elapsed_seconds"] = round(perf_counter() - started, 3)
            result["captured_seq"] = store.status()["captured_tx_seq"]
            if stage == 0:
                assert result["to_seq"] == 0 and result["captured_seq"] == 2
                baseline_path = path
            report["stages"].append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        assert baseline_path is not None
        verify_graph(baseline_path, baseline, cases, MONTH, contract)
        check_recovery(settings, reader, source, program, snapshot.cursor)
        export_sql(name, database, output)
        report.update(
            passed=True,
            real_binlog=True,
            concurrent_capture_verified=True,
            old_graph_unchanged=True,
            source_database=database,
        )
    except Exception as error:
        report["error_type"] = type(error).__name__
        if isinstance(error, UpdateError):
            report["error_code"] = error.code
        raise
    finally:
        try:
            report["graph_cleanup"] = cleanup(output, credentials)
        finally:
            if (output / "container-id").exists():
                command("docker", "stop", name)
                started_container = True
            report["container_reclaimed"] = started_container
            write_json(output / "report.json", report)
    return report


def restore_and_delete(settings: dict, removed: dict) -> None:
    with closing(pymysql.connect(**settings)) as connection:
        with connection.cursor() as cursor:
            columns = list(removed)
            cursor.execute(
                "INSERT INTO graph_edge_mapping ("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join(["%s"] * len(columns))
                + ")",
                tuple(removed.values()),
            )
            cursor.execute(
                "UPDATE resume SET deleted_at='2026-11-09 10:00:00' WHERE id=10"
            )
        connection.commit()


def check_recovery(
    settings: dict,
    reader: dict,
    source: MySQLSource,
    program: UpdateProgram,
    baseline: Cursor,
) -> None:
    before = program.store.status()["captured_tx_seq"]
    with closing(pymysql.connect(**settings)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE graph_edge_mapping SET standard_entity_id=999999 WHERE id=10001"
            )
        connection.rollback()
    assert program.capture(source) == {"captured": 0, "replayed": 0}
    replay = MySQLSource(
        reader, program.store.contract, source.generation, cursor=baseline
    )
    assert program.capture(replay) == {"captured": 0, "replayed": 3}
    assert program.store.status()["captured_tx_seq"] == before
    resumed = MySQLSource(
        reader,
        program.store.contract,
        source.generation,
        cursor=Cursor.model_validate(program.store.status()["capture_cursor"]),
    )
    assert program.capture(resumed) == {"captured": 0, "replayed": 0}
    with sqlite3.connect(program.store.path) as state:
        assert (
            state.execute("SELECT count(*) FROM rq_cdc_transaction").fetchone()[0] == 3
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    args = parser.parse_args()
    print(
        json.dumps(run(args.output.resolve(), args.credentials), ensure_ascii=False),
        flush=True,
    )
