"""UUID 来源的只读查询适配。表约定集中于此；图不保存姓名及来源自由文本。"""

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    MetaData,
    String,
    Table,
    and_,
    func,
    literal,
    select,
    union_all,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.engine import Engine

from relationship_query.domain.models import Fact
from relationship_query.infrastructure.mysql import RemoteMySQL
from relationship_query.infrastructure.projection_source_schema import PREFIX, SLOTS
from relationship_query.infrastructure.read_model import QueryTables
from relationship_query.infrastructure.source_graph_model import SourceManifest
from relationship_query.infrastructure.source_read_model import _identity, _month, _string

MODEL = "uuid-relations-v5"
MAPPING = "graph_edge_mapping"
ENTITY_TAGS = {
    "graph_company_entity": ("company", "organization"),
    "graph_school_entity": ("school", "school"),
    "graph_major_entity": ("major", "major"),
}
FACT_TYPES = {
    "worked_at": ("employment", "company_name", "work_experience", "company"),
    "studied_at": ("education", "school_name", "education_experience", "school"),
    "studied_major": ("major", "major", "education_experience", "major"),
}
NAMES = (
    *ENTITY_TAGS,
    MAPPING,
    *(name for p in PREFIX.values() for name in (p, *(f"{p}_{s}" for s in SLOTS))),
)


class UUIDManifest(SourceManifest):
    format_version: Literal[3, 4, 5] = 3  # type: ignore[assignment]
    model: Literal["uuid-relations-v5"] = MODEL  # type: ignore[assignment]
    graph_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    sql_guard: Literal["mutation-sequence-v1"] | None = None
    source_endpoint: RemoteMySQL | None = None

    @model_validator(mode="after")
    def check_guard_mode(self) -> "UUIDManifest":
        if (self.format_version in (4, 5)) != (self.sql_guard is not None):
            raise ValueError("清单版本与 SQL 发布标记模式不一致")
        if (self.format_version == 5) != (self.source_endpoint is not None):
            raise ValueError("清单版本与远程 MySQL 端点模式不一致")
        return self


def mock_schema() -> MetaData:
    """只给迁移演练建所需四表，不宣称是上游完整 DDL／发布契约。"""
    schema = MetaData()
    for table, (tag, _) in ENTITY_TAGS.items():
        Table(
            table,
            schema,
            Column("id", String(36), primary_key=True),
            Column("standard_name", String(255), nullable=False),
            Column(f"{tag}_code", String(128), nullable=False),
            Column("is_deleted", BigInteger, nullable=False),
            mysql_charset="utf8mb4",
        )
    Table(
        MAPPING,
        schema,
        Column("id", BigInteger, primary_key=True, autoincrement=False),
        Column("source_system", String(16), nullable=False),
        Column("source_table", String(64), nullable=False),
        Column("source_field_id", BigInteger, nullable=False),
        Column("source_field", String(64), nullable=False),
        Column("source_person_id", BigInteger, nullable=False),
        Column("standard_entity_id", String(36), nullable=False),
        Column("edge_type", String(32), nullable=False),
        Column("created_at", DATETIME(fsp=6)),
        Column("updated_at", DATETIME(fsp=6)),
        Column("deleted_at", DATETIME(fsp=6)),
        mysql_charset="utf8mb4",
    )
    return schema


def reflect(engine: Engine) -> MetaData:
    schema = MetaData()
    for name in NAMES:
        Table(name, schema, autoload_with=engine)
    return schema


def query_tables(schema: MetaData) -> QueryTables:
    people, sources, facts, entities, aliases = [], [], [], [], []
    mapping = schema.tables[MAPPING]
    for table, (_, kind) in ENTITY_TAGS.items():
        e = schema.tables[table]
        entities.append(
            select(
                _string(e.c.id).label("id"),
                literal(kind).label("type"),
                e.c.standard_name.label("name"),
                func.json_array(type_=JSON).label("aliases"),
            ).where(e.c.is_deleted == 0)
        )
        aliases.append(
            select(_string(e.c.id).label("entity_id"), e.c.standard_name.label("name")).where(
                e.c.is_deleted == 0
            )
        )
    for source, prefix in PREFIX.items():
        p = schema.tables[prefix]
        identity = _identity(f"p:{source}:", p.c.id)
        people.append(
            select(
                identity.label("id"),
                p.c.name,
                p.c.city,
                p.c.job_name.label("headline"),
                p.c.deleted_at.is_(None).label("active"),
                p.c.serial_number,
            )
        )
        sources.append(select(identity.label("person_id"), literal(source).label("source")))
        for edge, (kind, field, suffix, tag) in FACT_TYPES.items():
            raw = schema.tables[f"{prefix}_{suffix}"]
            m = mapping.alias(f"{source}_{edge}")
            joined = raw.join(
                m,
                and_(
                    m.c.source_system == source,
                    m.c.source_table == raw.name,
                    m.c.source_field_id == raw.c.id,
                    m.c.source_field == field,
                    m.c.source_person_id == raw.c[f"{source}_id"],
                    m.c.edge_type == edge,
                    m.c.deleted_at.is_(None),
                ),
            ).join(p, p.c.id == raw.c[f"{source}_id"])
            entity = schema.tables[f"graph_{tag}_entity"]
            joined = joined.join(
                entity, and_(entity.c.id == m.c.standard_entity_id, entity.c.is_deleted == 0)
            )
            work = kind == "employment"
            facts.append(
                select(
                    _identity("slot:", m.c.id).label("id"),
                    identity.label("person_id"),
                    literal(kind).label("type"),
                    _string(m.c.standard_entity_id).label("entity_id"),
                    literal(None).label("role_id"),
                    _month(raw.c.start_date).label("start_month"),
                    _month(raw.c.end_date).label("end_month"),
                    (raw.c.is_employed == 1 if work else literal(False)).label("is_current"),
                    and_(raw.c.deleted_at.is_(None), p.c.deleted_at.is_(None)).label("active"),
                    literal(source).label("source_system"),
                    _identity(raw.name + ":", raw.c.id).label("source_record_id"),
                    _identity(f"{source}:{raw.name}:", raw.c.id).label("experience_key"),
                    (raw.c.position_title if work else literal(None)).label("position_title"),
                    (literal(None) if work else raw.c.education_level).label("education_level"),
                    (literal(None) if work else raw.c.is_regular_enrollment).label(
                        "is_regular_enrollment"
                    ),
                ).select_from(joined)
            )
    return QueryTables(
        people=union_all(*people).subquery("uuid_people"),
        sources=union_all(*sources).subquery("uuid_sources"),
        facts=union_all(*facts).subquery("uuid_facts"),
        entities=union_all(*entities).subquery("uuid_entities"),
        aliases=union_all(*aliases).subquery("uuid_aliases"),
    )


def projection_records(
    data: dict[str, list[dict[str, Any]]], reference_month: int
) -> tuple[list[dict], list[dict]]:
    """预检全量冻结样例，再转换允许入图的属性；不计算人物关系。"""
    nodes, edges, targets, persons = [], [], {}, {}
    for table, (tag, _) in ENTITY_TAGS.items():
        seen = set()
        for row in data[table]:
            key = row["id"]
            if str(UUID(key)) != key or key in targets or key in seen:
                raise ValueError(f"UUID_COLLISION_OR_FORMAT {table}/{key}")
            seen.add(key)
            targets[key] = (tag, row)
            if row["is_deleted"] not in (0, 1):
                raise ValueError("INVALID_DELETE_FLAG")
            if not row["is_deleted"]:
                props = {"name": row["standard_name"], f"{tag}_code": row[f"{tag}_code"]}
                if not all(isinstance(v, str) and v for v in props.values()):
                    raise ValueError("MISSING_ENTITY_NAME_OR_CODE")
                nodes.append(dict(vid=f"e:{key}", type=tag, properties=props))
    for source, prefix in PREFIX.items():
        serials = set()
        for row in data[prefix]:
            if type(row["id"]) is not int or not 0 < row["id"] < 2**63:
                raise ValueError("INVALID_PERSON_ID")
            identity = f"p:{source}:{row['id']}"
            if identity in persons or not row["serial_number"] or row["serial_number"] in serials:
                raise ValueError("PERSON_ID_OR_SERIAL_INVALID")
            serials.add(row["serial_number"])
            persons[identity] = row
            if not row["deleted_at"]:
                nodes.append(
                    dict(
                        vid=identity,
                        type="person",
                        properties=dict(source_system=source, serial_number=row["serial_number"]),
                    )
                )
    ranks, slots = set(), set()
    for m in data[MAPPING]:
        rank = m["id"]
        slot = tuple(
            m[k] for k in ("source_system", "source_table", "source_field_id", "source_field")
        )
        if type(rank) is not int or not 0 < rank < 2**63 or rank in ranks or slot in slots:
            raise ValueError("DUPLICATE_RANK_OR_SLOT")
        ranks.add(rank)
        slots.add(slot)
        if any(
            type(m[k]) is not int or not 0 < m[k] < 2**63
            for k in ("source_field_id", "source_person_id")
        ):
            raise ValueError(f"INVALID_SOURCE_KEY {rank}")
        kind, field, suffix, tag = FACT_TYPES[m["edge_type"]]
        source = m["source_system"]
        table = f"{PREFIX[source]}_{suffix}"
        if m["source_table"] != table or m["source_field"] != field:
            raise ValueError(f"INVALID_SLOT {rank}")
        raw = next((r for r in data[table] if r["id"] == m["source_field_id"]), None)
        person_id = f"p:{source}:{m['source_person_id']}"
        target = targets.get(m["standard_entity_id"])
        if (
            raw is None
            or raw[f"{source}_id"] != m["source_person_id"]
            or person_id not in persons
            or not target
            or target[0] != tag
        ):
            raise ValueError(f"SOURCE_REFERENCE_MISMATCH {rank}")
        if (
            m["deleted_at"]
            or raw["deleted_at"]
            or persons[person_id]["deleted_at"]
            or target[1]["is_deleted"]
        ):
            continue
        start, end = raw["start_date"], raw["end_date"]

        def month(v: Any) -> int | None:
            return (
                (v.year * 100 + v.month)
                if isinstance(v, datetime)
                else (int(v[:4]) * 100 + int(v[5:7]) if v else None)
            )

        if start and end and start > end:
            raise ValueError(f"DAY_INTERVAL_INVALID {rank}")
        current = kind == "employment" and raw["is_employed"] == 1
        if kind == "employment" and raw["is_employed"] not in (1, 2):
            raise ValueError(f"CURRENT_STATE_INVALID {rank}")
        f = Fact(
            id=f"slot:{rank}",
            person_id=person_id,
            type=cast(Literal["employment", "education", "major"], kind),
            entity_id=m["standard_entity_id"],
            start_month=month(start),
            end_month=month(end),
            is_current=current,
            source_system=source,
            source_record_id=f"{table}:{raw['id']}",
        )
        if current and f.start_month and f.start_month > reference_month:
            raise ValueError(f"CURRENT_START_IN_FUTURE {rank}")
        props = dict(experience_key=f"{source}:{table}:{raw['id']}")
        if kind == "employment":
            props.update(
                position_title=raw["position_title"],
                start_month=f.start_month,
                end_month=f.end_month,
                is_current=current,
            )
        else:
            props.update(
                education_level=raw["education_level"],
                is_regular_enrollment=raw["is_regular_enrollment"],
                start_month=f.start_month,
                end_month=f.end_month,
            )
        edges.append(
            dict(
                source=person_id,
                target=f"e:{f.entity_id}",
                type=m["edge_type"],
                rank=rank,
                properties=props,
            )
        )
    return nodes, edges
