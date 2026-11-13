"""六张归一表的模拟输入与薄转换；原履历结构明确为本轮补造。"""

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

from relationship_query.domain.models import Dataset, Entity, Person
from relationship_query.infrastructure.source_trial import (
    Kind,
    LocalSeed,
    MockMapping,
    MockSource,
    RawExperience,
    SampleEntity,
    build_mock_source,
    convert_source,
)

KINDS = {"company": "org", "school": "school", "major": "major"}
TABLES = {kind: f"graph_{kind}" for kind in KINDS}
MAPPING = "graph_expert_name_mapping"
STAMP = datetime(2026, 11, 5, 0, 0, 0, 123456)


def identity(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, "relationship-handoff-mock/" + value))


def management(*, compact: bool = False) -> dict[str, Any]:
    result = dict(source_updated_at=STAMP, sync_batch_id=1, synced_at=STAMP, is_deleted=0)
    if not compact:
        result.update(source_created_at=STAMP, deleted_at=None)
    return result


def make_fixture(document_sha256: str) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    kinds: list[tuple[Kind, str, int]] = [
        ("company", "公司", 6),
        ("school", "学校", 5),
        ("major", "专业", 3),
    ]
    sampled = [
        SampleEntity(
            id=identity(f"{kind}:{i}"),
            kind=kind,
            name=f"模拟标准{label}{i + 1}",
            aliases=[f"模拟旧称{label}{i + 1}"],
            status="已核验",
        )
        for kind, label, count in kinds
        for i in range(count)
    ]
    relation = dict(
        id=identity("relation:0"),
        parent_company_id=identity("company:0"),
        child_company_id=identity("company:1"),
        relation_type="子公司",
        verification_status="已核验",
    )
    seed = LocalSeed(entities=sampled, mappings=[], relations=[relation])
    source = build_mock_source(seed, document_sha256)
    source.version = "handoff-trial-v1-" + document_sha256[:12]
    rows = _entity_rows(sampled)
    # 名称不唯一、官方码不唯一，均按文档保留，不以名称识别身份。
    duplicate = {
        **rows["graph_company"][0],
        "id": identity("company:duplicate"),
        "company_code": "C_DUP",
        "entity_key": "mock.company.duplicate",
        "child_company_codes": 0,
        "parent_company_codes": 0,
    }
    rows["graph_company"].append(duplicate)
    rows["graph_company_relation"] = [{**relation, **management()}]
    mapping_rows, experiences = _source_rows(source)
    rows[MAPPING] = mapping_rows
    _mapping_variations(mapping_rows)
    counts = {name: len(items) for name, items in rows.items()}
    rows["graph_sync_batch"] = [
        dict(
            id=1,
            source_project_id="mock-local-no-supabase",
            sync_mode="full",
            status="completed",
            started_at=STAMP,
            snapshot_at=STAMP,
            finished_at=STAMP,
            expected_counts=counts,
            actual_counts=counts,
            error_message=None,
        )
    ]
    raw = dict(
        schema_kind="synthetic-raw-experiences-not-upstream-ddl",
        version=source.version,
        reference_month=source.reference_month,
        people=[p.model_dump() for p in source.people],
        roles=[e.model_dump() for e in source.entities if e.type == "role"],
        experiences=experiences,
        slots=source.slots,
    )
    return rows, raw


def _entity_rows(entities: list[SampleEntity]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES.values()}
    for entity in entities:
        index = len(rows[TABLES[entity.kind]])
        row = dict(
            id=entity.id,
            entity_key=f"mock.{entity.kind}.{index}",
            standard_name=entity.name,
            verification_status=entity.status,
            **{f"{entity.kind}_code": f"{entity.kind[0].upper()}{index:03d}"},
            **management(),
        )
        if entity.kind != "major":
            row["former_names"] = entity.aliases
        if entity.kind == "company":
            row.update(
                child_company_codes=["C001"] if index == 0 else None if index == 2 else 0,
                parent_company_codes=["C000"] if index == 1 else None if index == 2 else 0,
            )
        if entity.kind == "school":
            row.update(
                official_code="mock-shared-official-code", country_region="模拟地区", city=None
            )
        rows[TABLES[entity.kind]].append(row)
    return rows


def _source_rows(source: MockSource) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mappings, experiences = [], []
    counters: Counter[str] = Counter()
    originals = {m.raw_id: m for m in source.mappings}
    names = {e.id: e.name for e in source.entities}
    for record in source.experiences:
        namespace = f"mock.{record.source_system}.{record.type}"
        counters[namespace] += 1
        source_id = str(counters[namespace])
        match = originals[record.id]
        mappings.append(
            dict(
                id=identity("mapping:" + record.fact_id),
                entity_type=match.kind,
                source_namespace=namespace,
                source_record_id=source_id,
                item_no=1,
                raw_name=names[match.target_id],
                company_id=None,
                school_id=None,
                major_id=None,
                processing_status="已匹配",
                **management(compact=True),
            )
        )
        mappings[-1][f"{match.kind}_id"] = match.target_id.split(":", 1)[1]
        if record.type == "education":
            mappings.append(
                {
                    **mappings[-1],
                    "id": identity("major:" + record.fact_id),
                    "entity_type": "major",
                    "school_id": None,
                    "major_id": identity("major:0"),
                    "raw_name": "模拟专业原文",
                }
            )
        experiences.append(
            dict(
                source_namespace=namespace,
                source_record_id=source_id,
                normalization_name=names[match.target_id],
                **record.model_dump(exclude={"id"}),
            )
        )
    return mappings, experiences


def _mapping_variations(rows: list[dict[str, Any]]) -> None:
    base = next(r for r in rows if r["entity_type"] == "company")
    rows.append({**base, "id": identity("mapping:repeat"), "item_no": 2})
    for status in ("待处理", "待确认", "无有效名称", "处理失败", "部分匹配"):
        rows.append(
            {
                **base,
                "id": identity("mapping:" + status),
                "company_id": None,
                "processing_status": status,
            }
        )
    rows.append({**base, "id": identity("mapping:deleted"), "is_deleted": 1})


def inspect_source(rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    """数据库外的逻辑核对；不自动修正 JSON、删除状态或层级信息。"""
    issues = []
    batches = {r["id"]: r for r in rows["graph_sync_batch"]}
    for name, records in rows.items():
        if name == "graph_sync_batch":
            continue
        for record in records:
            UUID(record["id"])
            batch = batches.get(record["sync_batch_id"])
            if batch is None or batch["status"] != "completed":
                raise ValueError(f"UNPUBLISHED_BATCH {name}/{record['id']}")
    companies = {r["company_code"]: r for r in rows["graph_company"] if not r["is_deleted"]}
    pairs = {
        (r["parent_company_id"], r["child_company_id"])
        for r in rows["graph_company_relation"]
        if not r["is_deleted"]
    }
    for row in companies.values():
        for field in ("child_company_codes", "parent_company_codes"):
            value = row[field]
            if value is None or type(value) is int and value == 0:
                continue
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise ValueError(f"INVALID_COMPANY_CODES {row['id']}/{field}")
            if len(value) != len(set(value)) or set(value) - companies.keys():
                raise ValueError(f"UNKNOWN_OR_DUPLICATE_COMPANY_CODE {row['id']}/{field}")
            for code in value:
                pair = (row["id"], companies[code]["id"])
                if field == "parent_company_codes":
                    pair = pair[::-1]
                if pair not in pairs:
                    issues.append(dict(code="COMPANY_RELATION_MISMATCH", record_id=row["id"]))
    return issues


def convert_tables(
    rows: dict[str, list[dict[str, Any]]], raw: dict[str, Any]
) -> tuple[Dataset, list[dict[str, Any]], list[dict[str, str]]]:
    issues = inspect_source(rows)
    entities = [Entity.model_validate(r) for r in raw["roles"]]
    targets = {}
    for kind in ("company", "school"):
        for row in rows[TABLES[kind]]:
            if row["is_deleted"]:
                continue
            aliases = row["former_names"] or []
            if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
                raise ValueError(f"INVALID_ALIASES {row['id']}")
            entity = Entity(
                id=f"{KINDS[kind]}:{row['id']}",
                type="organization" if kind == "company" else "school",
                name=row["standard_name"],
                aliases=aliases,
            )
            targets[(kind, row["id"])] = entity.id
            entities.append(entity)
    records = {(r["source_namespace"], r["source_record_id"]): r for r in raw["experiences"]}
    if len(records) != len(raw["experiences"]):
        raise ValueError("DUPLICATE_RAW_EXPERIENCE")
    groups: dict[tuple[str, str], list[MockMapping]] = defaultdict(list)
    for row in rows[MAPPING]:
        if row["is_deleted"] or row["processing_status"] != "已匹配":
            issues.append(dict(code="MAPPING_NOT_CONSUMED", record_id=row["id"]))
            continue
        key = (row["source_namespace"], row["source_record_id"])
        if key not in records:
            raise ValueError(f"RAW_EXPERIENCE_NOT_FOUND {row['id']}")
        if row["entity_type"] == "major":
            issues.append(dict(code="MAJOR_NOT_A_ROLE_OR_SCHOOL", record_id=row["id"]))
            continue
        kind = row["entity_type"]
        if row["raw_name"] != records[key]["normalization_name"]:
            raise ValueError(f"STALE_RAW_NAME {row['id']}")
        target = targets.get((kind, row[f"{kind}_id"]))
        if target is None:
            raise ValueError(f"MAPPING_TARGET_MISSING_OR_DELETED {row['id']}")
        groups[key].append(
            MockMapping(id=row["id"], raw_id=_raw_id(key), kind=kind, target_id=target)
        )
    experiences = []
    for key, record in records.items():
        if key not in groups:
            issues.append(dict(code="RAW_WITHOUT_PUBLISHED_MAPPING", record_id=_raw_id(key)))
            continue
        experiences.append(
            RawExperience(
                id=_raw_id(key),
                **{
                    k: v
                    for k, v in record.items()
                    if k not in {"source_namespace", "source_record_id", "normalization_name"}
                },
            )
        )
    source = MockSource(
        version=raw["version"],
        reference_month=raw["reference_month"],
        people=[Person.model_validate(p) for p in raw["people"]],
        entities=entities,
        experiences=experiences,
        mappings=[m for group in groups.values() for m in group],
        slots=raw["slots"],
    )
    dataset, trace = convert_source(source)
    for item in trace:
        item["origin"] = "six-table-mysql-roundtrip-and-synthetic-raw-experiences"
    return dataset, trace, issues


def _raw_id(key: tuple[str, str]) -> str:
    return "mock-raw:" + ":".join(quote(part, safe="") for part in key)
