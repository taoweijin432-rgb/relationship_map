"""原表与三表的只读 SQL 适配；只创建 SELECT 子查询，不建视图或事实表。"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, MetaData, String, Table, and_, cast, func, literal, select, union_all
from sqlalchemy.engine import Connection, Engine

from relationship_query.infrastructure.projection_source_schema import (
    ALIAS,
    ENTITY,
    MAPPING,
    PREFIX,
    SLOTS,
)
from relationship_query.infrastructure.read_model import QueryTables
from relationship_query.services.query import QueryError

SNAPSHOT_ROW_LIMIT = 10_000
SOURCE_NAMES = (
    ENTITY,
    ALIAS,
    MAPPING,
    *(name for prefix in PREFIX.values() for name in (prefix, *(f"{prefix}_{s}" for s in SLOTS))),
)


def reflect_source(engine: Engine) -> MetaData:
    schema = MetaData()
    for name in SOURCE_NAMES:
        Table(name, schema, autoload_with=engine)
    return schema


def snapshot(
    connection: Connection, schema: MetaData, names: tuple[str, ...] = SOURCE_NAMES
) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for name in names:
        table = schema.tables[name]
        rows = connection.execute(select(table).order_by(table.c.id).limit(SNAPSHOT_ROW_LIMIT + 1))
        result[name] = [dict(row) for row in rows.mappings()]
        if len(result[name]) > SNAPSHOT_ROW_LIMIT:
            raise QueryError("SOURCE_LIMIT", "原表集成实验单表上限为 10000 条，不作为生产接入", 422)
    return result


def source_digest(value: Any) -> str:
    def serial(item: Any) -> str:
        if isinstance(item, datetime):
            return item.isoformat(timespec="microseconds")
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError(type(item).__name__)

    return hashlib.sha256(json.dumps(value, sort_keys=True, default=serial).encode()).hexdigest()


def _string(value: Any) -> Any:
    return cast(value, String(128)).collate("utf8mb4_bin")


def _identity(prefix: str, value: Any) -> Any:
    return func.concat(prefix, _string(value)).collate("utf8mb4_bin")


def _month(value: Any) -> Any:
    return func.year(value) * 100 + func.month(value)


def query_tables(schema: MetaData) -> QueryTables:
    person_queries, source_queries, fact_queries = [], [], []
    mapping = schema.tables[MAPPING]
    for source, prefix in PREFIX.items():
        person = schema.tables[prefix]
        identity = _identity(f"p:{source}:", person.c.id)
        person_queries.append(
            select(
                identity.label("id"),
                person.c.name,
                person.c.city,
                person.c.job_name.label("headline"),
                person.c.deleted_at.is_(None).label("active"),
            )
        )
        source_queries.append(select(identity.label("person_id"), literal(source).label("source")))
        for suffix, field, kind in (
            ("work_experience", "company_name", "employment"),
            ("education_experience", "school_name", "education"),
        ):
            raw = schema.tables[f"{prefix}_{suffix}"]
            target, role = (
                mapping.alias(f"{source}_{kind}_target"),
                mapping.alias(f"{source}_{kind}_role"),
            )
            joined = raw.join(
                target,
                and_(
                    target.c.source_system == source,
                    target.c.source_table == raw.name,
                    target.c.source_field_id == raw.c.id,
                    target.c.source_field == field,
                    target.c.source_person_id == raw.c[f"{source}_id"],
                    target.c.deleted_at.is_(None),
                ),
            ).join(person, person.c.id == raw.c[f"{source}_id"])
            if kind == "employment":
                joined = joined.outerjoin(
                    role,
                    and_(
                        role.c.source_system == source,
                        role.c.source_table == raw.name,
                        role.c.source_field_id == raw.c.id,
                        role.c.source_field == "position_title",
                        role.c.source_person_id == raw.c[f"{source}_id"],
                        role.c.deleted_at.is_(None),
                    ),
                )
            fact_queries.append(
                select(
                    _identity("slot:", target.c.id).label("id"),
                    identity.label("person_id"),
                    literal(kind).label("type"),
                    _string(target.c.entity_id).label("entity_id"),
                    (_string(role.c.entity_id) if kind == "employment" else literal(None)).label(
                        "role_id"
                    ),
                    _month(raw.c.start_date).label("start_month"),
                    _month(raw.c.end_date).label("end_month"),
                    (raw.c.is_employed == 1 if kind == "employment" else literal(False)).label(
                        "is_current"
                    ),
                    and_(raw.c.deleted_at.is_(None), person.c.deleted_at.is_(None)).label("active"),
                    literal(source).label("source_system"),
                    _identity(raw.name + ":", raw.c.id).label("source_record_id"),
                ).select_from(joined)
            )

    entity, alias = schema.tables[ENTITY], schema.tables[ALIAS]
    alias_names = (
        select(func.json_arrayagg(alias.c.alias_name, type_=JSON))
        .where(
            alias.c.entity_id == entity.c.id,
            alias.c.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    entities = select(
        _string(entity.c.id).label("id"),
        entity.c.entity_type.label("type"),
        entity.c.canonical_name.label("name"),
        func.coalesce(alias_names, func.json_array(), type_=JSON).label("aliases"),
    ).where(
        entity.c.deleted_at.is_(None), entity.c.entity_type.in_(["organization", "school", "role"])
    )
    aliases = select(
        _string(alias.c.entity_id).label("entity_id"), alias.c.alias_name.label("name")
    ).where(alias.c.deleted_at.is_(None))
    return QueryTables(
        people=union_all(*person_queries).subquery("source_people"),
        sources=union_all(*source_queries).subquery("source_sources"),
        facts=union_all(*fact_queries).subquery("source_facts"),
        entities=entities.subquery("source_entities"),
        aliases=aliases.subquery("source_aliases"),
    )
