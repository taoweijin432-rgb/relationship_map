"""只消费本地样例的薄适配；云端采样与业务查询均不在此模块执行。"""

import hashlib
import json
import shlex
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from relationship_query.domain.models import Dataset, Entity, Fact, Person, Source
from relationship_query.domain.validation import validate_payload
from relationship_query.infrastructure.fixtures import make_dataset
from relationship_query.infrastructure.sqlite import load_dataset, open_engine

Kind = Literal["company", "school", "major"]
PREFIX = {"company": "org", "school": "school", "major": "major"}


class TrialInputError(ValueError):
    pass


class LocalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SampleEntity(LocalModel):
    id: str
    kind: Kind
    name: str
    aliases: list[str]
    status: str
    merged_into_id: str | None = None

    @property
    def key(self) -> str:
        return f"{PREFIX[self.kind]}:{self.id}"


class SampleMapping(LocalModel):
    id: str
    kind: Kind
    status: str
    target_id: str | None
    original_id: str | None
    namespace: str | None


class LocalSeed(LocalModel):
    entities: list[SampleEntity]
    mappings: list[SampleMapping]
    relations: list[dict[str, Any]]


def read_seed(payload: dict[str, Any]) -> LocalSeed:
    """当前物理字段只在采样边界出现；不是未来上游契约。"""
    entities = []
    for kind in ("company", "school", "major"):
        for row in payload.get(f"{kind}_standard", []):
            names = [row.get("short_name"), *(row.get("former_names") or [])]
            entities.append(
                SampleEntity(
                    id=row["id"],
                    kind=kind,
                    name=row["standard_name"],
                    aliases=sorted({n.strip() for n in names if n and n.strip()}),
                    status=row["verification_status"],
                    merged_into_id=row.get("merged_into_id"),
                )
            )
    for row in payload.get("name_mapping", []):
        targets = [k for k in ("company", "school", "major") if row.get(f"{k}_id")]
        if len(targets) > 1 or targets and targets[0] != row["entity_type"]:
            raise TrialInputError(f"采样映射目标数量或类型错误：{row['id']}")
    mappings = [
        SampleMapping(
            id=r["id"],
            kind=r["entity_type"],
            status=r["processing_status"],
            target_id=r.get(f"{r['entity_type']}_id"),
            original_id=r.get("original_database_id"),
            namespace=r.get("source_namespace"),
        )
        for r in payload.get("name_mapping", [])
    ]
    return LocalSeed(
        entities=entities, mappings=mappings, relations=payload.get("company_relation", [])
    )


def _unique(values: list[str], label: str) -> None:
    if len(set(values)) != len(values) or any(not v.strip() for v in values):
        raise TrialInputError(f"{label} 标识为空或重复")


def inspect_seed(seed: LocalSeed) -> list[dict[str, str]]:
    _unique([e.key for e in seed.entities], "采样实体")
    _unique([m.id for m in seed.mappings], "采样映射")
    entities = {(e.kind, e.id): e for e in seed.entities}
    issues = []
    for entity in seed.entities:
        if not entity.name.strip():
            raise TrialInputError(f"实体 {entity.key} 缺少名称")
        visited, current = set(), entity
        while current.status == "已合并":
            key = (current.kind, current.id)
            if key in visited:
                raise TrialInputError(f"实体合并存在环：{entity.key}")
            visited.add(key)
            target = entities.get((current.kind, current.merged_into_id or ""))
            if target is None:
                raise TrialInputError(f"合并目标缺失：{current.key}")
            current = target
        if entity.status == "已合并":
            issues.append(dict(code="MERGED_ENTITY", record_id=entity.key, category="source"))
    for mapping in seed.mappings:
        target = entities.get((mapping.kind, mapping.target_id or ""))
        if mapping.target_id and target is None or mapping.status == "已匹配" and target is None:
            raise TrialInputError(f"映射目标缺失：{mapping.id}")
        for condition, code in (
            (mapping.status != "已匹配", "UNCONFIRMED_MAPPING"),
            (not mapping.original_id or not mapping.namespace, "MISSING_ORIGINAL_KEY"),
        ):
            if condition:
                issues.append(dict(code=code, record_id=mapping.id, category="source"))
    for relation in seed.relations:
        for side in ("parent", "child"):
            if ("company", relation[f"{side}_company_id"]) not in entities:
                raise TrialInputError(f"组织关系引用缺失：{relation['id']}")
    groups: dict[tuple[str, str, str], list[SampleMapping]] = defaultdict(list)
    for mapping in seed.mappings:
        if mapping.original_id and mapping.namespace:
            groups[(mapping.kind, mapping.namespace, mapping.original_id)].append(mapping)
    for group in groups.values():
        if len(group) > 1:
            code = (
                "MULTIPLE_TARGETS" if len({m.target_id for m in group}) > 1 else "REPEATED_MAPPING"
            )
            issues.append(dict(code=code, record_id=group[0].id, category="source"))
    return issues


def _entity_slots(seed: LocalSeed) -> dict[str, SampleEntity]:
    result = {}
    for kind, count in (("company", 6), ("school", 5)):
        selected = sorted(
            (e for e in seed.entities if e.kind == kind and e.status == "已核验"),
            key=lambda e: e.id,
        )
        if kind == "company" and seed.relations:
            pair = seed.relations[0]
            priority = [pair["parent_company_id"], pair["child_company_id"]]
            selected.sort(key=lambda e: (priority.index(e.id) if e.id in priority else 2, e.id))
        if len(selected) < count:
            raise TrialInputError(f"演练需要至少 {count} 个已核验 {kind}")
        result.update({f"{PREFIX[kind]}:{i}": e for i, e in enumerate(selected[:count])})
    return result


class RawExperience(LocalModel):
    id: str
    fact_id: str
    person_id: str
    type: Literal["employment", "education"]
    role_id: str | None = None
    start_month: int | None = None
    end_month: int | None = None
    is_current: bool = False
    active: bool = True
    source_system: Source


class MockMapping(LocalModel):
    id: str
    raw_id: str
    kind: Literal["company", "school"]
    target_id: str
    status: str = "已匹配"
    sampled_mapping_id: str | None = None


class MockSource(LocalModel):
    version: str
    reference_month: int
    people: list[Person]
    entities: list[Entity]
    experiences: list[RawExperience]
    mappings: list[MockMapping]
    slots: dict[str, str]
    synthetic_fields: list[str] = Field(
        default_factory=lambda: [
            "people",
            "experience_ownership",
            "dates",
            "roles",
            "source_labels",
            "mock_mappings",
        ]
    )


def build_mock_source(seed: LocalSeed, digest: str) -> MockSource:
    slots = _entity_slots(seed)
    original = make_dataset(60, seed=42)
    entities = [e for e in original.entities if e.type == "role"]
    entities.extend(
        Entity(
            id=e.key,
            type="organization" if e.kind == "company" else "school",
            name=e.name,
            aliases=e.aliases,
        )
        for e in slots.values()
    )
    people = [p.model_copy(update={"name": "模拟·" + p.name}) for p in original.people]
    template_ids = {(m.kind, m.target_id): m.id for m in seed.mappings if m.status == "已匹配"}
    raw, mappings = [], []
    for fact in original.facts:
        values = fact.model_dump(
            exclude={
                "id",
                "entity_id",
                "source_record_id",
                "experience_key",
                "position_title",
                "education_level",
                "is_regular_enrollment",
            }
        )
        if fact.id in {"f:000014:work", "f:000015:work"}:
            values.update(
                start_month=202012 if "000014" in fact.id else 202101,
                end_month=202101,
                is_current=False,
            )
            slot = slots["org:2"]
        else:
            slot = slots[fact.entity_id]
        raw_id = "mock-raw:" + fact.id
        raw.append(RawExperience(id=raw_id, fact_id="trial:" + fact.id, **values))
        mappings.append(
            MockMapping(
                id="mock-map:" + fact.id,
                raw_id=raw_id,
                kind="company" if fact.type == "employment" else "school",
                target_id=slot.key,
                sampled_mapping_id=template_ids.get((slot.kind, slot.id)),
            )
        )
    return MockSource(
        version="source-trial-v1-" + digest[:12],
        reference_month=202611,
        people=people,
        entities=entities,
        experiences=raw,
        mappings=mappings,
        slots={k: v.key for k, v in slots.items()},
    )


def convert_source(source: MockSource) -> tuple[Dataset, list[dict[str, Any]]]:
    """只有本地模拟归一关联参与虚构经历归属，采样原库 ID 不进入事实。"""
    _unique([r.id for r in source.experiences], "模拟原经历")
    _unique([r.fact_id for r in source.experiences], "模拟事实")
    _unique([m.id for m in source.mappings], "模拟映射")
    raw_ids = {r.id for r in source.experiences}
    entities = {e.id: e for e in source.entities}
    grouped: dict[str, list[MockMapping]] = defaultdict(list)
    for mapping in source.mappings:
        if mapping.raw_id not in raw_ids:
            raise TrialInputError(f"模拟映射引用的原经历不存在：{mapping.id}")
        grouped[mapping.raw_id].append(mapping)
    facts, provenance = [], []
    for record in source.experiences:
        if not record.id.startswith("mock-raw:") or not record.fact_id.startswith("trial:"):
            raise TrialInputError("模拟原经历和事实必须使用模拟前缀")
        matches = [m for m in grouped[record.id] if m.status == "已匹配"]
        if not matches or len({(m.kind, m.target_id) for m in matches}) != 1:
            raise TrialInputError(f"模拟原经历归一目标缺失或不唯一：{record.id}")
        mapping = matches[0]
        target = entities.get(mapping.target_id)
        expected = "organization" if record.type == "employment" else "school"
        if (
            target is None
            or target.type != expected
            or mapping.kind != ("company" if record.type == "employment" else "school")
        ):
            raise TrialInputError(f"模拟原经历的归一实体类型错误：{record.id}")
        facts.append(
            Fact(
                id=record.fact_id,
                entity_id=target.id,
                source_record_id=record.id,
                **record.model_dump(exclude={"id", "fact_id"}),
            )
        )
        provenance.append(
            dict(
                fact_id=record.fact_id,
                mock_raw_id=record.id,
                entity_id=target.id,
                mock_mapping_ids=[m.id for m in matches],
                sampled_mapping_ids=sorted(
                    {m.sampled_mapping_id for m in matches if m.sampled_mapping_id}
                ),
                duplicate_mappings_collapsed=len(matches) - 1,
                experience_is_synthetic=True,
            )
        )
    names = {e.id: e.name for e in source.entities}
    people = []
    for person in source.people:
        works = [
            f for f in facts if f.person_id == person.id and f.type == "employment" and f.active
        ]
        latest = max(works, key=lambda f: (f.is_current, f.start_month or 0)) if works else None
        headline = (
            f"{names[latest.entity_id]} · {names.get(latest.role_id or '', '职位待补全')}"
            if latest
            else "职业信息待补全"
        )
        people.append(person.model_copy(update={"headline": headline}))
    dataset = Dataset(
        version=source.version,
        reference_month=source.reference_month,
        people=people,
        entities=source.entities,
        facts=facts,
    )
    _, report = validate_payload(dataset.model_dump())
    if not report.valid:
        raise TrialInputError(report.model_dump_json())
    return dataset, provenance


def prepare_trial(input_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("输出必须为新目录，不覆盖既有数据")
    content = input_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise TrialInputError("本地样例必须是 JSON 对象")
    seed = read_seed(payload)
    issues = inspect_seed(seed)
    source = build_mock_source(seed, digest)
    dataset, provenance = convert_source(source)
    _, validation = validate_payload(dataset.model_dump())
    report = dict(
        data_mode="mock",
        status="ready",
        data_version=dataset.version,
        input_sha256=digest,
        captured_at=payload.get("captured_at"),
        people=len(dataset.people),
        facts=len(dataset.facts),
        entities=len(dataset.entities),
        sampled_entities=len(seed.entities),
        sampled_mappings=len(seed.mappings),
        issue_counts=dict(Counter(i["code"] for i in issues)),
        slots=source.slots,
        cloud_access=False,
        synthetic_fields=source.synthetic_fields,
        warning="真实实体名称用于模拟；所有人物、归属、日期、职位和人物关系均为虚构。",
    )
    # 所有输入和转换先成功，才创建新库；ready 最后发布，失败不伪装为可运行批次。
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {
        "mock-source.json": source.model_dump(),
        "dataset.json": dataset.model_dump(),
        "provenance.json": provenance,
        "source-issues.json": issues,
        "preflight.json": validation.model_dump(),
    }
    for name, value in artifacts.items():
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    engine = open_engine(output / "query.sqlite")
    try:
        load_dataset(engine, dataset)
    finally:
        engine.dispose()
    (output / ".env").write_text(
        "unset RELATIONSHIP_MYSQL_URL RELATIONSHIP_NEBULA_MANIFEST\n"
        "export RELATIONSHIP_DATABASE="
        + shlex.quote(str((output / "query.sqlite").resolve()))
        + "\n"
    )
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report
