"""从已校验、只读快照建立新图空间，逐批回读后才发布 ready manifest。"""

import json
import os
import secrets
import shlex
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from time import monotonic, perf_counter, sleep
from typing import Any

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Connection

from relationship_query.domain.models import Dataset, Entity, Fact
from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.graph_client import GraphClient, GraphDependencyError
from relationship_query.infrastructure.graph_model import (
    BLOCK_SIZE,
    ProjectionManifest,
    ReaderCredentials,
    ids_digest,
    literal,
    vid,
)
from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
)
from relationship_query.infrastructure.read_model import dataset_meta, facts, people
from relationship_query.infrastructure.snapshots import (
    iter_dataset_batches,
    open_snapshot,
    snapshot_digest,
    validate_snapshot,
)

EXPERIENCE = [
    "fact_id",
    "kind",
    "role_id",
    "start_month",
    "end_month",
    "is_current",
    "active",
    "source_system",
    "source_record_id",
]
PERSON = ["id", "name", "active", "expert", "resume", "entities", "checksum"]
ENTITY = ["id", "kind", "members", "blocks", "payload"]
SCHEMA = [
    "CREATE TAG projection(status string, projection_id string, source_digest string, "
    "data_version string, reference_month int, format_version int)",
    "CREATE TAG person(id string, name string, active bool, expert bool, resume bool, "
    "entities int, checksum string)",
    "CREATE TAG entity(id string, kind string, members int, blocks int, payload string)",
    "CREATE TAG roster(entity_id string, part int, member_count int, checksum string)",
    "CREATE EDGE experience(fact_id string, kind string, role_id string, start_month int, "
    "end_month int, is_current bool, active bool, source_system string, source_record_id string)",
    "CREATE EDGE affiliated(entity_id string, kind string)",
    "CREATE EDGE member(person_id string)",
]


class ProjectionWriter:
    def __init__(self, session: Any) -> None:
        self.session = session
        self.statements = 0

    def _write(self, prefix: str, lines: list[str]) -> None:
        for offset in range(0, len(lines), 500):
            query(self.session, prefix + ",".join(lines[offset : offset + 500]), wait=True)
            self.statements += 1

    def vertices(self, tag: str, columns: list[str], rows: list[tuple[str, list[Any]]]) -> None:
        self._write(
            f"INSERT VERTEX {tag}({','.join(columns)}) VALUES ",
            [
                f"{literal(identity)}:({','.join(literal(value) for value in values)})"
                for identity, values in rows
            ],
        )

    def edges(
        self, edge: str, columns: list[str], rows: list[tuple[str, str, int, list[Any]]]
    ) -> None:
        self._write(
            f"INSERT EDGE {edge}({','.join(columns)}) VALUES ",
            [
                f"{literal(a)}->{literal(b)}@{rank}:"
                f"({','.join(literal(value) for value in values)})"
                for a, b, rank, values in rows
            ],
        )


def _experience(fact: Fact) -> list[Any]:
    return [
        fact.id,
        fact.type,
        fact.role_id,
        fact.start_month,
        fact.end_month,
        fact.is_current,
        fact.active,
        fact.source_system,
        fact.source_record_id,
    ]


def _batch_records(batch: Dataset) -> tuple[list, list, list]:
    histories: dict[str, list[Fact]] = defaultdict(list)
    for fact in batch.facts:
        histories[fact.person_id].append(fact)
    persons: list[tuple[str, list[Any]]] = []
    affiliations: list[tuple[str, str, int, list[Any]]] = []
    experiences: list[tuple[str, str, int, list[Any]]] = []
    for person in batch.people:
        ordered = sorted(histories[person.id], key=lambda fact: fact.id)
        related = sorted({fact.entity_id for fact in ordered if person.active and fact.active})
        persons.append(
            (
                vid("p", person.id),
                [
                    person.id,
                    person.name,
                    person.active,
                    "expert" in person.sources,
                    "resume" in person.sources,
                    len(related),
                    ids_digest(related),
                ],
            )
        )
        mapping = {fact.entity_id: fact.type for fact in ordered}
        affiliations.extend(
            (vid("p", person.id), vid("e", entity), 0, [entity, mapping[entity]])
            for entity in related
        )
        experiences.extend(
            (vid("p", person.id), vid("e", fact.entity_id), rank, _experience(fact))
            for rank, fact in enumerate(ordered)
        )
    return persons, affiliations, experiences


def _audit_batch(session: Any, persons: list, experiences: list, affiliations: list) -> None:
    for offset in range(0, len(persons), 100):
        segment = persons[offset : offset + 100]
        ids = {identity for identity, _ in segment}
        selection = ",".join(literal(identity) for identity, _ in segment)
        rows = query(
            session,
            f"FETCH PROP ON person {selection} "
            "YIELD id(vertex) AS vid, properties(vertex) AS props",
        )
        expected = {identity: dict(zip(PERSON, values)) for identity, values in segment}
        if {row["vid"]: row["props"] for row in rows} != expected:
            raise ValueError("图人物回读对账失败，投影不发布")
        rows = query(
            session,
            f"GO FROM {selection} OVER experience YIELD src(edge) AS source, "
            "dst(edge) AS target, rank(edge) AS fact_rank, properties(edge) AS props",
        )
        expected_edges = {
            (a, b, rank): dict(zip(EXPERIENCE, values))
            for a, b, rank, values in experiences
            if a in ids
        }
        actual = {(row["source"], row["target"], row["fact_rank"]): row["props"] for row in rows}
        if actual != expected_edges or len(actual) != len(rows):
            raise ValueError("图事实回读对账失败，投影不发布")
        rows = query(
            session,
            f"GO FROM {selection} OVER affiliated "
            "YIELD src(edge) AS source, dst(edge) AS target, properties(edge) AS props",
        )
        expected_related = {
            (a, b): dict(zip(["entity_id", "kind"], values))
            for a, b, _rank, values in affiliations
            if a in ids
        }
        if {(row["source"], row["target"]): row["props"] for row in rows} != expected_related:
            raise ValueError("图人物邻接回读对账失败，投影不发布")


def _rosters(source: Connection, writer: ProjectionWriter, dictionary: dict) -> tuple[int, int]:
    members = source.execute(
        select(facts.c.entity_id, facts.c.person_id)
        .join(people, people.c.id == facts.c.person_id)
        .where(people.c.active.is_(True), facts.c.active.is_(True))
        .distinct()
        .order_by(facts.c.entity_id, facts.c.person_id)
    )
    blocks = total = 0
    for entity_id, grouped in groupby(members, key=lambda row: row.entity_id):
        identities = [row.person_id for row in grouped]
        count = (len(identities) + BLOCK_SIZE - 1) // BLOCK_SIZE
        entity = dictionary[entity_id]
        writer.vertices(
            "entity",
            ENTITY,
            [
                (
                    vid("e", entity_id),
                    [entity_id, entity.type, len(identities), count, entity.model_dump_json()],
                )
            ],
        )
        for part in range(count):
            ids = identities[part * BLOCK_SIZE : (part + 1) * BLOCK_SIZE]
            block = vid("b", entity_id, part)
            writer.vertices(
                "roster",
                ["entity_id", "part", "member_count", "checksum"],
                [(block, [entity_id, part, len(ids), ids_digest(ids)])],
            )
            writer.edges(
                "member", ["person_id"], [(block, vid("p", person), 0, [person]) for person in ids]
            )
            rows = query(
                writer.session,
                f"GO FROM {literal(block)} OVER member "
                "YIELD properties(edge).person_id AS person_id LIMIT [129]",
            )
            if sorted(row["person_id"] for row in rows) != ids:
                raise ValueError("图成员分块回读对账失败，投影不发布")
            blocks += 1
        total += len(identities)
    return blocks, total


def _validate_vids(source: Connection) -> None:
    for batch in iter_dataset_batches(source):
        for person in batch.people:
            vid("p", person.id)
        for entity in batch.entities:
            vid("e", entity.id)
            vid("b", entity.id, 9_999_999)


def _reader_account(session: Any, output: Path) -> ReaderCredentials:
    credentials = ReaderCredentials(
        username="rq_" + secrets.token_hex(6), password=SecretStr(secrets.token_hex(12))
    )
    file = output / "reader-credentials.json"
    descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(
            {
                **credentials.model_dump(mode="json"),
                "password": credentials.password.get_secret_value(),
            },
            stream,
        )
    query(
        session,
        f"CREATE USER {credentials.username} WITH PASSWORD "
        f"'{credentials.password.get_secret_value()}'",
    )
    return credentials


def project_snapshot(path: Path, output: Path) -> ProjectionManifest:
    if output.exists():
        raise FileExistsError("使用新的投影目录，不覆盖已发布批次")
    started = perf_counter()
    source = open_snapshot(path)
    try:
        with source.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            counts = validate_snapshot(connection)
            _validate_vids(connection)
            digest = snapshot_digest(connection)
            meta = connection.execute(select(dataset_meta)).one()
            space = "relationship_lab_projection_" + secrets.token_hex(6)
            output.mkdir(parents=True, exist_ok=False)
            with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
                manifest, credentials = _project(
                    connection,
                    session,
                    output,
                    space,
                    meta.version,
                    meta.reference_month,
                    digest,
                    counts,
                )
            _wait_reader(manifest, credentials)
            report = {
                **manifest.model_dump(),
                "elapsed_ms": round((perf_counter() - started) * 1000, 2),
            }
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            (output / "manifest.json").write_text(manifest.model_dump_json(indent=2))

            (output / ".env").write_text(
                "export RELATIONSHIP_NEBULA_MANIFEST="
                + shlex.quote(str((output / "manifest.json").resolve()))
                + "\nexport RELATIONSHIP_DATABASE="
                + shlex.quote(str(path.resolve()))
                + "\n"
            )
            return manifest
    finally:
        source.dispose()


def _project(
    source: Connection,
    session: Any,
    output: Path,
    space: str,
    version: str,
    month: int,
    digest: str,
    counts: dict[str, int],
) -> tuple[ProjectionManifest, ReaderCredentials]:
    query(
        session,
        f"CREATE SPACE `{space}` (partition_num=1,replica_factor=1,vid_type=FIXED_STRING(128))",
    )
    query(session, f"USE `{space}`", wait=True)
    for statement in SCHEMA:
        query(session, statement, wait=True)
    writer = ProjectionWriter(session)
    marker_columns = [
        "status",
        "projection_id",
        "source_digest",
        "data_version",
        "reference_month",
        "format_version",
    ]
    writer.vertices(
        "projection",
        marker_columns,
        [("meta|projection", ["building", space, digest, version, month, 1])],
    )
    (output / "building.json").write_text(
        json.dumps(
            {"space": space, "data_version": version, "source_digest": digest, "status": "building"}
        )
    )
    dictionary: dict[str, Entity] = {}
    membership = 0
    for batch in iter_dataset_batches(source):
        if not dictionary:
            dictionary = {entity.id: entity for entity in batch.entities}
            writer.vertices(
                "entity",
                ENTITY,
                [
                    (vid("e", entity.id), [entity.id, entity.type, 0, 0, entity.model_dump_json()])
                    for entity in batch.entities
                ],
            )
        persons, affiliations, experiences = _batch_records(batch)
        writer.vertices("person", PERSON, persons)
        writer.edges("experience", EXPERIENCE, experiences)
        writer.edges("affiliated", ["entity_id", "kind"], affiliations)
        _audit_batch(session, persons, experiences, affiliations)
        membership += len(affiliations)
    blocks, members = _rosters(source, writer, dictionary)
    if membership != members:
        raise ValueError("人物邻接与实体成员数量不一致")
    credentials = _reader_account(session, output)
    query(session, f"GRANT ROLE GUEST ON `{space}` TO {credentials.username}")
    writer.vertices(
        "projection",
        marker_columns,
        [("meta|projection", ["ready", space, digest, version, month, 1])],
    )
    counts.update(
        entities=len(dictionary),
        blocks=blocks,
        memberships=members,
        experience_edges=counts["facts"],
        auxiliary_edges=2 * members,
        write_statements=writer.statements,
    )
    return ProjectionManifest(
        space=space,
        projection_id=space,
        data_version=version,
        reference_month=month,
        source_digest=digest,
        counts=counts,
    ), credentials


def _wait_reader(manifest: ProjectionManifest, credentials: ReaderCredentials) -> None:
    deadline = monotonic() + 60
    client = GraphClient(manifest, credentials)
    try:
        while True:
            try:
                client.check_version(PathBudget(3000, 5000))
                return
            except GraphDependencyError:
                if monotonic() >= deadline:
                    raise
                sleep(1)
    finally:
        client.close()
