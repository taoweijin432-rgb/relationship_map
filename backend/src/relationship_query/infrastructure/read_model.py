"""实验查询读模型，独立于上游物理表；SQLite 与 MySQL 共享逻辑结构。"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Index, Integer, MetaData, String, Table
from sqlalchemy.dialects.mysql import VARCHAR


def _string(length: int = 255) -> String:
    # MySQL 使用无尾空格折叠的二进制排序，人物键不受服务端默认 ai_ci 影响。
    return String().with_variant(VARCHAR(length, collation="utf8mb4_0900_bin"), "mysql")


schema = MetaData()
people = Table(
    "demo_person",
    schema,
    Column("id", _string(128), primary_key=True),
    Column("name", _string(), index=True),
    Column("city", _string()),
    Column("headline", _string()),
    Column("active", Boolean),
)
sources = Table(
    "demo_person_source",
    schema,
    Column("person_id", ForeignKey("demo_person.id"), primary_key=True),
    Column("source", _string(), primary_key=True),
)
entities = Table(
    "demo_entity",
    schema,
    Column("id", _string(128), primary_key=True),
    Column("type", _string(), index=True),
    Column("name", _string(), index=True),
    Column("aliases", JSON),
)
aliases = Table(
    "demo_entity_alias",
    schema,
    Column("entity_id", ForeignKey("demo_entity.id"), primary_key=True),
    Column("name", _string(), primary_key=True),
)
facts = Table(
    "demo_fact",
    schema,
    Column("id", _string(128), primary_key=True),
    Column("person_id", ForeignKey("demo_person.id")),
    Column("type", _string()),
    Column("entity_id", ForeignKey("demo_entity.id")),
    Column("role_id", ForeignKey("demo_entity.id"), nullable=True),
    Column("start_month", Integer, nullable=True),
    Column("end_month", Integer, nullable=True),
    Column("is_current", Boolean),
    Column("active", Boolean),
    Column("source_system", _string()),
    Column("source_record_id", _string()),
)
dataset_meta = Table(
    "demo_dataset",
    schema,
    Column("id", Integer, primary_key=True),
    Column("version", _string()),
    Column("reference_month", Integer),
)
Index("ix_demo_fact_person", facts.c.person_id, facts.c.active, facts.c.entity_id)
Index("ix_demo_fact_entity", facts.c.entity_id, facts.c.active, facts.c.person_id)
Index("ix_demo_fact_company_role", facts.c.entity_id, facts.c.role_id, facts.c.active)


@dataclass(frozen=True)
class QueryTables:
    """查询所需的逻辑列，可由演示表或原表的只读子查询提供。"""

    people: Any = people
    sources: Any = sources
    entities: Any = entities
    aliases: Any = aliases
    facts: Any = facts
