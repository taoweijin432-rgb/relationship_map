"""已冻结实验源的轻量漂移标记。DML 触发器与源修改在同一事务提交。"""

from typing import Any

from sqlalchemy import BigInteger, Column, MetaData, String, Table, insert, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import ProgrammingError

from relationship_query.infrastructure.uuid_source import NAMES, UUIDManifest
from relationship_query.services.query import QueryError

GUARD_TABLE = "relationship_release_guard"
GUARD_VERSION = "mutation-sequence-v1"
schema = MetaData()
guard = Table(
    GUARD_TABLE,
    schema,
    Column("id", BigInteger, primary_key=True),
    Column("guard_version", String(64), nullable=False),
    Column("source_digest", String(64), nullable=False),
    Column("data_version", String(128), nullable=False),
    Column("reference_month", BigInteger, nullable=False),
    Column("mutation_seq", BigInteger, nullable=False),
    Column("state", String(16), nullable=False),
    mysql_engine="InnoDB",
)


def expected(manifest: UUIDManifest) -> dict[str, Any]:
    return dict(
        id=1,
        guard_version=GUARD_VERSION,
        source_digest=manifest.source_digest,
        data_version=manifest.data_version,
        reference_month=manifest.reference_month,
        mutation_seq=0,
        state="ready",
    )


def install(engine: Engine, manifest: UUIDManifest) -> None:
    """只在发布工具新建的实验库调用，现有发布库不得原位安装。"""
    schema.create_all(engine, checkfirst=False)
    with engine.begin() as connection:
        connection.execute(insert(guard), expected(manifest))
    with engine.connect() as connection:
        for index, name in enumerate(NAMES):
            for event in ("INSERT", "UPDATE", "DELETE"):
                trigger = f"rq_guard_{index}_{event.lower()}"
                connection.exec_driver_sql(
                    f"CREATE TRIGGER `{trigger}` AFTER {event} ON `{name}` FOR EACH ROW "
                    f"UPDATE `{GUARD_TABLE}` SET mutation_seq=mutation_seq+1 WHERE id=1"
                )
        rows = connection.exec_driver_sql(
            "SELECT TRIGGER_NAME,EVENT_OBJECT_TABLE,EVENT_MANIPULATION,ACTION_TIMING,"
            "ACTION_STATEMENT FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()"
        ).all()
        wanted = {
            (
                f"rq_guard_{i}_{event.lower()}",
                name,
                event,
                "AFTER",
                f"UPDATE `{GUARD_TABLE}` SET mutation_seq=mutation_seq+1 WHERE id=1",
            )
            for i, name in enumerate(NAMES)
            for event in ("INSERT", "UPDATE", "DELETE")
        }
        if set(tuple(row) for row in rows) != wanted:
            raise ValueError("发布库 DML 标记触发器未完整安装")


def verify(connection: Connection, manifest: UUIDManifest) -> None:
    try:
        row = connection.execute(select(guard).where(guard.c.id == 1)).mappings().first()
    except ProgrammingError as exc:
        if exc.orig is None or exc.orig.args[0] != 1146:
            raise
        row = None
    if row is None or dict(row) != expected(manifest):
        raise QueryError("SOURCE_VERSION_MISMATCH", "发布源已变化或标记不符，请停服重新发布", 409)


def verify_reader(connection: Connection, manifest: UUIDManifest) -> None:
    grants = list(connection.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER").scalars())
    allowed = ("GRANT USAGE ON *.* TO ", f"GRANT SELECT ON `{manifest.source_database}`.* TO ")
    if len(grants) != 2 or not all(
        any(grant.startswith(prefix) for prefix in allowed) and "WITH GRANT OPTION" not in grant
        for grant in grants
    ):
        raise ValueError("轻量发布源查询账号应仅有本库 SELECT 权限")
