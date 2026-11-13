"""同事六表设计的本机验证 DDL；不作为正式上游迁移。"""

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.schema import SchemaItem

schema = MetaData()


def uuid_column(name: str, *, target: str | None = None, primary: bool = False) -> Column:
    args = [ForeignKey(target)] if target else []
    return Column(
        name,
        mysql.CHAR(36, charset="ascii", collation="ascii_bin"),
        *args,
        primary_key=primary,
        nullable=not primary if target else False,
    )


def varchar(name: str, size: int, *, nullable: bool = False) -> Column:
    return Column(name, mysql.VARCHAR(size), nullable=nullable)


def management(*, compact: bool = False) -> list:
    columns: list[Any] = (
        []
        if compact
        else [
            Column("source_created_at", mysql.DATETIME(fsp=6), nullable=False),
        ]
    )
    columns.extend(
        [
            Column("source_updated_at", mysql.DATETIME(fsp=6), nullable=False),
            Column(
                "sync_batch_id",
                mysql.BIGINT(unsigned=True),
                ForeignKey("graph_sync_batch.id"),
                nullable=False,
                index=True,
            ),
            Column("synced_at", mysql.DATETIME(fsp=6), nullable=False),
            Column("is_deleted", mysql.TINYINT(unsigned=True), nullable=False, server_default="0"),
            CheckConstraint("is_deleted IN (0,1)"),
        ]
    )
    if not compact:
        columns.append(Column("deleted_at", mysql.DATETIME(fsp=6)))
    return columns


def table(name: str, *columns: SchemaItem) -> Table:
    return Table(
        name,
        schema,
        *columns,
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )


batch = table(
    "graph_sync_batch",
    Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
    varchar("source_project_id", 64),
    varchar("sync_mode", 16),
    varchar("status", 16),
    Column("started_at", mysql.DATETIME(fsp=6), nullable=False),
    Column("snapshot_at", mysql.DATETIME(fsp=6)),
    Column("finished_at", mysql.DATETIME(fsp=6)),
    Column("expected_counts", mysql.JSON(none_as_null=True)),
    Column("actual_counts", mysql.JSON(none_as_null=True)),
    Column("error_message", Text),
    CheckConstraint("sync_mode IN ('full','incremental')", name="ck_batch_mode"),
)


def entity_columns(kind: str) -> list:
    return [
        uuid_column("id", primary=True),
        varchar(f"{kind}_code", 64),
        varchar("entity_key", 128),
        varchar("standard_name", 255),
        UniqueConstraint(f"{kind}_code"),
        UniqueConstraint("entity_key"),
        Index(f"ix_{kind}_name", "standard_name"),
    ]


def json_array(name: str) -> list:
    return [
        Column(name, mysql.JSON(none_as_null=True)),
        CheckConstraint(f"{name} IS NULL OR JSON_TYPE({name}) = 'ARRAY'"),
    ]


def company_links(name: str) -> list:
    return [
        Column(name, mysql.JSON(none_as_null=True)),
        CheckConstraint(
            f"{name} IS NULL OR JSON_TYPE({name}) = 'ARRAY' OR "
            f"(JSON_TYPE({name}) = 'INTEGER' AND JSON_UNQUOTE({name}) = '0')"
        ),
    ]


company = table(
    "graph_company",
    *entity_columns("company"),
    *json_array("former_names"),
    varchar("verification_status", 64),
    *company_links("child_company_codes"),
    *company_links("parent_company_codes"),
    *management(),
)
school = table(
    "graph_school",
    *entity_columns("school"),
    *json_array("former_names"),
    varchar("official_code", 64, nullable=True),
    varchar("country_region", 128, nullable=True),
    varchar("city", 128, nullable=True),
    varchar("verification_status", 64),
    *management(),
)
major = table(
    "graph_major",
    *entity_columns("major"),
    varchar("verification_status", 64),
    *management(),
)
mapping = table(
    "graph_expert_name_mapping",
    uuid_column("id", primary=True),
    varchar("entity_type", 16),
    varchar("source_namespace", 128),
    varchar("source_record_id", 128),
    Column("item_no", mysql.INTEGER(unsigned=True), nullable=False),
    Column("raw_name", Text, nullable=False),
    uuid_column("company_id", target="graph_company.id"),
    uuid_column("school_id", target="graph_school.id"),
    uuid_column("major_id", target="graph_major.id"),
    varchar("processing_status", 64),
    *management(compact=True),
    CheckConstraint("item_no > 0", name="ck_mapping_item"),
    CheckConstraint("entity_type IN ('company','school','major')", name="ck_mapping_kind"),
    CheckConstraint(
        "processing_status IN ('待处理','已匹配','待确认','无有效名称','处理失败','部分匹配')",
        name="ck_mapping_status",
    ),
    CheckConstraint(
        "(entity_type='company' AND school_id IS NULL AND major_id IS NULL AND "
        "(processing_status<>'已匹配' OR company_id IS NOT NULL)) OR "
        "(entity_type='school' AND company_id IS NULL AND major_id IS NULL AND "
        "(processing_status<>'已匹配' OR school_id IS NOT NULL)) OR "
        "(entity_type='major' AND company_id IS NULL AND school_id IS NULL AND "
        "(processing_status<>'已匹配' OR major_id IS NOT NULL))",
        name="ck_mapping_target",
    ),
    Index("ix_mapping_source", "source_namespace", "source_record_id", "entity_type", "is_deleted"),
    *[
        Index(f"ix_mapping_{kind}", f"{kind}_id", "processing_status", "is_deleted")
        for kind in ("company", "school", "major")
    ],
)
relation = table(
    "graph_company_relation",
    uuid_column("id", primary=True),
    Column(
        "parent_company_id",
        mysql.CHAR(36, charset="ascii", collation="ascii_bin"),
        ForeignKey("graph_company.id"),
        nullable=False,
    ),
    Column(
        "child_company_id",
        mysql.CHAR(36, charset="ascii", collation="ascii_bin"),
        ForeignKey("graph_company.id"),
        nullable=False,
    ),
    varchar("relation_type", 32),
    varchar("verification_status", 64),
    *management(),
    UniqueConstraint("parent_company_id", "child_company_id", "relation_type"),
    CheckConstraint("parent_company_id <> child_company_id", name="ck_relation_self"),
    CheckConstraint("relation_type IN ('子公司','分公司')", name="ck_relation_type"),
    Index("ix_relation_child", "child_company_id", "verification_status", "is_deleted"),
)


def ddl() -> str:
    """只生成本模块六表 DDL，不执行 Word 中的文本。"""
    statements = []
    for item in schema.sorted_tables:
        statements.append(str(CreateTable(item).compile(dialect=mysql.dialect())).strip() + ";")
        statements.extend(
            str(CreateIndex(i).compile(dialect=mysql.dialect())) + ";"
            for i in sorted(item.indexes, key=lambda index: index.name or "")
        )
    return (
        "-- 本地虚构数据实验；批次 status 未定义枚举，未自行添加约束。\n\n"
        + "\n\n".join(statements)
        + "\n"
    )
