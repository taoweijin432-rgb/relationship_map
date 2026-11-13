"""三表文档的实验定义；额外约束是本轮建议，不补造缺失的合并／发布列。"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    MetaData,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import DATETIME, VARCHAR

schema = MetaData()
ENTITY = "Relationship_Graph_entity"
ALIAS = "Relationship_Graph_entity_alias"
MAPPING = "Relationship_Graph_edge_mapping"
TYPES = ("organization", "role", "project", "school", "major")
SLOTS = {
    "work_experience": {"company_name": "worked_at", "position_title": "held_role"},
    "project_experience": {"project_title": "participated_in", "company_name": "collaborated with"},
    "education_experience": {"school_name": "studied_at", "major": "studied_major"},
}
PREFIX = {"expert": "experts", "resume": "resume"}


def stamps() -> list[Column]:
    return [
        Column(
            "created_at",
            DATETIME(fsp=6),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP(6)"),
        ),
        Column(
            "updated_at",
            DATETIME(fsp=6),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        ),
        Column("deleted_at", DATETIME(fsp=6)),
    ]


entity = Table(
    ENTITY,
    schema,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("entity_type", VARCHAR(32), nullable=False),
    Column("canonical_name", VARCHAR(255), nullable=False),
    *stamps(),
    CheckConstraint("id > 0"),
    CheckConstraint("entity_type IN ('organization','role','project','school','major')"),
    Index("ix_dictionary_name_type", "canonical_name", "entity_type", "deleted_at"),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_bin",
)
alias = Table(
    ALIAS,
    schema,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("entity_id", BigInteger, ForeignKey(f"{ENTITY}.id"), nullable=False),
    Column("alias_name", VARCHAR(255), nullable=False),
    *stamps(),
    CheckConstraint("id > 0"),
    UniqueConstraint("entity_id", "alias_name"),
    Index("ix_alias_lookup", "alias_name", "deleted_at"),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_bin",
)
mapping = Table(
    MAPPING,
    schema,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("source_system", VARCHAR(16), nullable=False),
    Column("source_table", VARCHAR(64), nullable=False),
    Column("source_field_id", BigInteger, nullable=False),
    Column("source_field", VARCHAR(64), nullable=False),
    Column("source_person_id", BigInteger, nullable=False),
    Column("entity_id", BigInteger, ForeignKey(f"{ENTITY}.id"), nullable=False),
    Column("edge_type", VARCHAR(64), nullable=False),
    *stamps(),
    CheckConstraint("id > 0 AND source_field_id > 0 AND source_person_id > 0"),
    UniqueConstraint("source_system", "source_table", "source_field_id", "source_field"),
    CheckConstraint(
        " OR ".join(
            f"(source_system='{source}' AND source_table='{prefix}_{suffix}' "
            f"AND source_field='{field}' AND edge_type='{edge}')"
            for source, prefix in PREFIX.items()
            for suffix, fields in SLOTS.items()
            for field, edge in fields.items()
        ),
        name="ck_source_slot_role",
    ),
    # 本机实测：含可空 deleted_at 的复合外键支持索引存在漏检，使用单列支持索引。
    Index("ix_edge_target", "entity_id"),
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_bin",
)
