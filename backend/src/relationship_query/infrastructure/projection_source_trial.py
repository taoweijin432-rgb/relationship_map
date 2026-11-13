"""六表归一来源→三表→真实形状原表的独立模拟；不自动治理实体。"""

import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from relationship_query.domain.models import validate_month
from relationship_query.infrastructure.mysql import open_mysql_engine
from relationship_query.infrastructure.projection_source_schema import (
    ALIAS,
    ENTITY,
    MAPPING,
    PREFIX,
    SLOTS,
)

FIELD_TYPES = {
    "worked_at": "organization",
    "held_role": "role",
    "participated_in": "project",
    "collaborated with": "organization",
    "studied_at": "school",
    "studied_major": "major",
}


def open_projection_engine(value: str, *, writable: bool = False) -> Engine:
    engine = open_mysql_engine(value, writable=writable)
    configure_projection_engine(engine)
    return engine


def configure_projection_engine(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def configure(connection: Any, _record: Any) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@SESSION.sql_mode")
            modes = set(cursor.fetchone()[0].split(",")) - {""}
            modes.add("STRICT_TRANS_TABLES")
            cursor.execute("SET SESSION sql_mode=%s", (",".join(sorted(modes)),))
            cursor.execute("SET SESSION time_zone='+00:00'")


def clean_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def make_projection_rows(
    six: dict[str, list[dict[str, Any]]],
    raw: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {ENTITY: [], ALIAS: [], MAPPING: []}
    bridge = []
    for kind, entity_type in (
        ("company", "organization"),
        ("school", "school"),
        ("major", "major"),
    ):
        for item in six[f"graph_{kind}"]:
            if item["is_deleted"]:
                continue
            entity_id = _add_entity(
                rows, entity_type, item["standard_name"], item.get("former_names") or []
            )
            bridge.append(
                dict(source_table=f"graph_{kind}", source_uuid=item["id"], entity_id=entity_id)
            )
    roles = {r["id"]: _add_entity(rows, "role", r["name"], []) for r in raw["roles"]}
    resolved = {(b["source_table"], b["source_uuid"]): b["entity_id"] for b in bridge}
    normalized = defaultdict(list)
    for item in six["graph_expert_name_mapping"]:
        if not item["is_deleted"] and item["processing_status"] == "已匹配":
            key = (item["source_namespace"], item["source_record_id"], item["entity_type"])
            normalized[key].append(item)
    _raw_people(rows, raw)
    for item in raw["experiences"]:
        source = item["source_system"]
        prefix = PREFIX[source]
        suffix = "work_experience" if item["type"] == "employment" else "education_experience"
        table = f"{prefix}_{suffix}"
        record = dict(
            id=int(item["source_record_id"]),
            **{f"{source}_id": int(item["person_id"].split(":")[-1])},
            start_date=_date(item["start_month"]),
            end_date=_date(item["end_month"]),
            deleted_at=_date(202611) if not item["active"] else None,
        )
        person = next(p for p in rows[prefix] if p["id"] == record[f"{source}_id"])
        if person["deleted_at"]:
            record["deleted_at"] = person["deleted_at"]
        field = "company_name" if item["type"] == "employment" else "school_name"
        kind = "company" if item["type"] == "employment" else "school"
        target = _normalized_target(normalized, item, kind, resolved, rows)
        record[field] = item["normalization_name"]
        if kind == "company":
            record.update(
                position_title=next(r["name"] for r in raw["roles"] if r["id"] == item["role_id"]),
                is_employed=1 if item["is_current"] else 2,
            )
            secondary_field, secondary_id = "position_title", roles[item["role_id"]]
        else:
            major = _normalized_target(normalized, item, "major", resolved, rows)
            record.update(
                major=normalized[(item["source_namespace"], item["source_record_id"], "major")][0][
                    "raw_name"
                ],
                create_by=0,
            )
            secondary_field, secondary_id = "major", major
        rows.setdefault(table, []).append(record)
        _add_slot(rows, source, table, record, field, target, record["deleted_at"])
        _add_slot(rows, source, table, record, secondary_field, secondary_id, record["deleted_at"])
    _raw_projects(rows, raw, resolved)
    return rows, bridge


def _add_entity(rows: dict, kind: str, name: str, aliases: list[str]) -> int:
    entity_id = 301 + len(rows[ENTITY])
    rows[ENTITY].append(dict(id=entity_id, entity_type=kind, canonical_name=name))
    for value in sorted({clean_name(n) for n in [name, *aliases] if clean_name(n)}):
        _add_alias(rows, entity_id, value)
    return entity_id


def _add_alias(rows: dict, entity_id: int, value: str) -> None:
    if not any(r["entity_id"] == entity_id and r["alias_name"] == value for r in rows[ALIAS]):
        rows[ALIAS].append(dict(id=1 + len(rows[ALIAS]), entity_id=entity_id, alias_name=value))


def _normalized_target(groups: dict, item: dict, kind: str, bridge: dict, rows: dict) -> int:
    matches = groups[(item["source_namespace"], item["source_record_id"], kind)]
    ids = {m[f"{kind}_id"] for m in matches}
    if len(ids) != 1:
        raise ValueError(f"UPSTREAM_TARGET_NOT_UNIQUE {item['fact_id']}/{kind}")
    entity_id = bridge[(f"graph_{kind}", next(iter(ids)))]
    for match in matches:
        _add_alias(rows, entity_id, clean_name(match["raw_name"]))
    return entity_id


def _raw_people(rows: dict, raw: dict) -> None:
    for source, table in PREFIX.items():
        rows[table] = [
            dict(
                id=int(p["id"].split(":")[-1]),
                serial_number=f"{source[0]}{int(p['id'].split(':')[-1]):018d}",
                name=p["name"],
                interview_nickname="模拟访谈",
                company="模拟主表显示公司",
                job_name="模拟主表显示职位",
                background="仅虚构数据",
                source_type=99,
                deleted_at=_date(202611) if not p["active"] else None,
            )
            for p in raw["people"]
            if source in p["sources"]
        ]


def _raw_projects(rows: dict, raw: dict, bridge: dict) -> None:
    organization = bridge[("graph_company", raw["slots"]["org:0"].split(":", 1)[1])]
    project = _add_entity(rows, "project", "模拟联合项目", [])
    for source, prefix in PREFIX.items():
        table = f"{prefix}_project_experience"
        rows[table] = []
        for index, person in enumerate(rows[prefix][:2], 1):
            record = dict(
                id=index,
                **{f"{source}_id": person["id"]},
                company_name=next(
                    e["canonical_name"] for e in rows[ENTITY] if e["id"] == organization
                ),
                project_title="模拟联合项目",
                start_date=_date(202001),
                end_date=_date(202212),
                deleted_at=None,
            )
            rows[table].append(record)
            _add_slot(rows, source, table, record, "company_name", organization, None)
            _add_slot(rows, source, table, record, "project_title", project, None)


def _add_slot(
    rows: dict, source: str, table: str, record: dict, field: str, target: int, deleted: object
) -> None:
    suffix = table[len(PREFIX[source]) + 1 :]
    rows[MAPPING].append(
        dict(
            id=1001 + len(rows[MAPPING]),
            source_system=source,
            source_table=table,
            source_field_id=record["id"],
            source_field=field,
            source_person_id=record[f"{source}_id"],
            entity_id=target,
            edge_type=SLOTS[suffix][field],
            deleted_at=deleted,
        )
    )


def _date(month: int | None) -> datetime | None:
    return datetime(month // 100, month % 100, 1) if month else None


def month(value: datetime | None) -> int | None:
    return value.year * 100 + value.month if value is not None else None


def projection_records(snapshot: dict[str, list[dict[str, Any]]]) -> tuple[list[dict], list[dict]]:
    entities = {r["id"]: r for r in snapshot[ENTITY] if not r.get("deleted_at")}
    aliases = {
        (r["entity_id"], clean_name(r["alias_name"]))
        for r in snapshot[ALIAS]
        if not r.get("deleted_at")
    }
    persons = {
        f"p:{source}:{p['id']}": p
        for source, table in PREFIX.items()
        for p in snapshot[table]
        if not p.get("deleted_at")
    }
    nodes = [dict(vid=k, type="person", name=p["name"]) for k, p in persons.items()]
    nodes.extend(
        dict(vid=f"e:{e['id']}", type=e["entity_type"], name=e["canonical_name"])
        for e in entities.values()
    )
    source_rows = {
        table: {r["id"]: r for r in snapshot[table]}
        for source, prefix in PREFIX.items()
        for suffix in SLOTS
        if (table := f"{prefix}_{suffix}")
    }
    slots = {}
    for mapping in snapshot[MAPPING]:
        if type(mapping["id"]) is not int or not 0 < mapping["id"] <= 2**63 - 1:
            raise ValueError(f"INVALID_RANK {mapping['id']}")
        key = (
            mapping["source_system"],
            mapping["source_table"],
            mapping["source_field_id"],
            mapping["source_field"],
        )
        if key in slots:
            raise ValueError(f"DUPLICATE_SLOT {mapping['id']}")
        slots[key] = mapping
    edges = []
    for mapping in snapshot[MAPPING]:
        if mapping.get("deleted_at"):
            continue
        source, table = mapping["source_system"], mapping["source_table"]
        if (
            source not in PREFIX
            or table not in source_rows
            or not table.startswith(PREFIX[source] + "_")
        ):
            raise ValueError(f"INVALID_SOURCE_SLOT {mapping['id']}")
        suffix = table[len(PREFIX[source]) + 1 :]
        edge_type = SLOTS[suffix].get(mapping["source_field"])
        if edge_type is None or mapping["edge_type"] != edge_type:
            raise ValueError(f"INVALID_EDGE_TYPE {mapping['id']}")
        raw = source_rows[table].get(mapping["source_field_id"])
        if not raw or raw.get("deleted_at"):
            raise ValueError(f"SOURCE_MISSING_OR_DELETED {mapping['id']}")
        person = f"p:{source}:{raw.get(source + '_id')}"
        if raw.get(source + "_id") != mapping["source_person_id"] or person not in persons:
            raise ValueError(f"SOURCE_PERSON_MISMATCH {mapping['id']}")
        entity = entities.get(mapping["entity_id"])
        if entity is None or entity["entity_type"] != FIELD_TYPES[edge_type]:
            raise ValueError(f"ENTITY_TYPE_OR_STATE {mapping['id']}")
        value = clean_name(raw.get(mapping["source_field"]) or "")
        if not value or (entity["id"], value) not in aliases:
            raise ValueError(f"STALE_OR_UNCONFIRMED_NAME {mapping['id']}")
        start, end = month(raw.get("start_date")), month(raw.get("end_date"))
        for date_month in (start, end):
            if date_month is not None:
                validate_month(date_month)
        if suffix == "work_experience" and raw["is_employed"] not in {1, 2}:
            raise ValueError(f"UNKNOWN_EMPLOYED_STATE {mapping['id']}")
        current = suffix == "work_experience" and raw["is_employed"] == 1
        if start and end and start > end or current and end is not None:
            raise ValueError(f"INVALID_DATE_STATE {mapping['id']}")
        role = slots.get((source, table, raw["id"], "position_title"))
        edges.append(
            dict(
                source=person,
                target=f"e:{entity['id']}",
                rank=mapping["id"],
                type=edge_type,
                properties=dict(
                    fact_id=f"slot:{mapping['id']}",
                    kind="employment"
                    if suffix == "work_experience"
                    else "education"
                    if suffix == "education_experience"
                    else "project",
                    active=True,
                    start_date=start,
                    end_date=end,
                    is_current=current,
                    role_id=role["entity_id"] if role and not role.get("deleted_at") else None,
                    source_system=source,
                    source_record_id=f"{table}:{raw['id']}",
                    source_table=table,
                    source_field_id=raw["id"],
                    source_field=mapping["source_field"],
                ),
            )
        )
    for source, prefix in PREFIX.items():
        for suffix, fields in SLOTS.items():
            table = f"{prefix}_{suffix}"
            for row in source_rows[table].values():
                if row.get("deleted_at"):
                    continue
                person = f"p:{source}:{row.get(source + '_id')}"
                if person not in persons:
                    raise ValueError(f"SOURCE_PERSON_MISMATCH {table}/{row['id']}")
                for field in fields:
                    key = (source, table, row["id"], field)
                    if clean_name(row.get(field) or "") and (
                        key not in slots or slots[key].get("deleted_at")
                    ):
                        raise ValueError(f"UNMAPPED_SLOT {table}/{row['id']}/{field}")
    return nodes, edges
