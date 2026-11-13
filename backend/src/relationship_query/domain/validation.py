"""逻辑数据集的共享预检，不依赖数据库，也不纠正输入数据。"""

from collections import defaultdict
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from relationship_query.domain.models import Dataset, Entity, Fact, Person


class ValidationIssue(BaseModel):
    code: str
    path: str
    message: str
    record_id: str | None = None
    related_ids: list[str] = Field(default_factory=list)


class ValidationCounts(BaseModel):
    person_count: int = 0
    entity_count: int = 0
    fact_count: int = 0
    error_count: int = 0
    warning_count: int = 0


class ValidationReport(BaseModel):
    report_version: Literal["1"] = "1"
    data_mode: Literal["mock"] = "mock"
    data_version: str | None = None
    valid: bool
    counts: ValidationCounts
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


class DatasetValidationError(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        first = report.errors[0]
        super().__init__(f"{first.code} {first.path}: {first.message}")


def validate_payload(payload: object) -> tuple[Dataset | None, ValidationReport]:
    """先做结构校验，再累计跨记录问题；结构无效时不推测缺失对象。"""
    try:
        dataset = Dataset.model_validate(payload)
    except ValidationError as exc:
        issues = [
            ValidationIssue(code="SCHEMA_ERROR", path=_pointer(error["loc"]), message=error["msg"])
            for error in exc.errors()
        ]
        return None, _report(payload, issues, [])
    errors = _identity_issues(dataset)
    errors.extend(_graph_id_issues(dataset))
    errors.extend(_fact_issues(dataset))
    warnings = _time_warnings(dataset)
    warnings.extend(_duplicate_fact_warnings(dataset))
    warnings.extend(_ambiguous_name_warnings(dataset.entities))
    return dataset, _report(dataset.model_dump(), errors, warnings)


def require_valid_dataset(dataset: Dataset) -> Dataset:
    checked, report = validate_payload(dataset.model_dump())
    if not report.valid:
        raise DatasetValidationError(report)
    assert checked is not None
    return checked


def input_error_report(code: str, message: str) -> ValidationReport:
    return _report(None, [ValidationIssue(code=code, path="/", message=message)], [])


def _pointer(parts: Iterable[str | int]) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _report(
    payload: object, errors: list[ValidationIssue], warnings: list[ValidationIssue]
) -> ValidationReport:
    data = payload if isinstance(payload, dict) else {}
    counts = {
        f"{singular}_count": len(data[plural]) if isinstance(data.get(plural), list) else 0
        for singular, plural in (("person", "people"), ("entity", "entities"), ("fact", "facts"))
    }
    version = data.get("version")
    return ValidationReport(
        valid=not errors,
        data_version=version if isinstance(version, str) else None,
        counts=ValidationCounts(**counts, error_count=len(errors), warning_count=len(warnings)),
        errors=errors,
        warnings=warnings,
    )


def _identity_issues(dataset: Dataset) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not dataset.version.strip():
        issues.append(
            ValidationIssue(code="EMPTY_VALUE", path="/version", message="数据版本不能为空")
        )
    groups: tuple[tuple[str, Iterable[Person | Entity | Fact]], ...] = (
        ("people", dataset.people),
        ("entities", dataset.entities),
        ("facts", dataset.facts),
    )
    for name, records in groups:
        issues.extend(_identifier_issues(name, records))
    issues.extend(_person_source_issues(dataset.people))
    issues.extend(_entity_definition_issues(dataset.entities))
    return issues


def _identifier_issues(
    name: str, records: Iterable[Person | Entity | Fact]
) -> list[ValidationIssue]:
    seen: set[str] = set()
    issues = []
    for index, record in enumerate(records):
        path = f"/{name}/{index}/id"
        if not record.id.strip():
            issues.append(
                ValidationIssue(code="EMPTY_VALUE", path=path, message="稳定标识不能为空")
            )
        if record.id in seen:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_ID", path=path, message="同类记录 ID 重复", record_id=record.id
                )
            )
        seen.add(record.id)
    return issues


def _person_source_issues(people: list[Person]) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            code="INVALID_SOURCES",
            path=f"/people/{index}/sources",
            message="人物来源不能为空或重复",
            record_id=person.id,
        )
        for index, person in enumerate(people)
        if not person.sources or len(set(person.sources)) != len(person.sources)
    ]


def _graph_id_issues(dataset: Dataset) -> list[ValidationIssue]:
    person_ids = {person.id for person in dataset.people}
    node_ids = person_ids | {e.id for e in dataset.entities if e.type != "role"}
    issues = [
        ValidationIssue(
            code="GRAPH_ID_COLLISION",
            path=f"/entities/{index}/id",
            message="人物与图实体标识冲突，需在适配时区分命名空间",
            record_id=entity.id,
        )
        for index, entity in enumerate(dataset.entities)
        if entity.type != "role" and entity.id in person_ids
    ]
    issues.extend(
        ValidationIssue(
            code="GRAPH_ID_COLLISION",
            path=f"/facts/{index}/id",
            message="经历生成的边标识与节点冲突，需在适配时区分命名空间",
            record_id=fact.id,
        )
        for index, fact in enumerate(dataset.facts)
        if f"edge:{fact.id}" in node_ids
    )
    return issues


def _entity_definition_issues(entities: list[Entity]) -> list[ValidationIssue]:
    issues = []
    for index, entity in enumerate(entities):
        if len(set(entity.aliases)) != len(entity.aliases):
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_ALIAS",
                    path=f"/entities/{index}/aliases",
                    message="同一实体的别名重复",
                    record_id=entity.id,
                )
            )
        if not entity.name.strip() or any(not alias.strip() for alias in entity.aliases):
            issues.append(
                ValidationIssue(
                    code="EMPTY_VALUE",
                    path=f"/entities/{index}",
                    message="标准名称和已有别名不能为空",
                    record_id=entity.id,
                )
            )
    return issues


def _fact_issues(dataset: Dataset) -> list[ValidationIssue]:
    people = {person.id: person for person in dataset.people}
    entities = {entity.id: entity for entity in dataset.entities}
    issues = []
    for index, fact in enumerate(dataset.facts):
        path = f"/facts/{index}"
        issues.extend(_fact_owner_issues(fact, path, people.get(fact.person_id)))
        issues.extend(_fact_entity_issues(fact, path, entities.get(fact.entity_id)))
        issues.extend(_employment_field_issues(fact, path, entities, dataset.reference_month))
        if not fact.source_record_id.strip():
            issues.append(
                ValidationIssue(
                    code="EMPTY_VALUE",
                    path=f"{path}/source_record_id",
                    message="来源经历定位不能为空",
                    record_id=fact.id,
                )
            )
    return issues


def _fact_owner_issues(fact: Fact, path: str, person: Person | None) -> list[ValidationIssue]:
    if person is None:
        return [
            ValidationIssue(
                code="MISSING_REFERENCE",
                path=f"{path}/person_id",
                message="经历引用的人物不存在",
                record_id=fact.id,
                related_ids=[fact.person_id],
            )
        ]
    if fact.source_system not in person.sources:
        return [
            ValidationIssue(
                code="SOURCE_UNMAPPED",
                path=f"{path}/source_system",
                message="经历来源未关联到该人物",
                record_id=fact.id,
            )
        ]
    return []


def _fact_entity_issues(fact: Fact, path: str, entity: Entity | None) -> list[ValidationIssue]:
    expected = "organization" if fact.type == "employment" else "school"
    if entity is not None and entity.type == expected:
        return []
    return [
        ValidationIssue(
            code="MISSING_REFERENCE" if entity is None else "ENTITY_TYPE_MISMATCH",
            path=f"{path}/entity_id",
            record_id=fact.id,
            message=f"经历必须关联已有的 {expected} 实体",
            related_ids=[fact.entity_id],
        )
    ]


def _employment_field_issues(
    fact: Fact, path: str, entities: dict[str, Entity], reference_month: int
) -> list[ValidationIssue]:
    issues = []
    if fact.role_id is not None:
        role = entities.get(fact.role_id)
        if role is None or role.type != "role":
            issues.append(
                ValidationIssue(
                    code="INVALID_ROLE_REFERENCE",
                    path=f"{path}/role_id",
                    message="职位必须引用已有的 role 实体",
                    record_id=fact.id,
                )
            )
    if fact.type == "education" and (fact.role_id is not None or fact.is_current):
        issues.append(
            ValidationIssue(
                code="INVALID_EMPLOYMENT_FIELDS",
                path=path,
                message="本轮教育经历不使用职位和当前任职标记",
                record_id=fact.id,
            )
        )
    if fact.is_current and fact.start_month and fact.start_month > reference_month:
        issues.append(
            ValidationIssue(
                code="INVALID_CURRENT_INTERVAL",
                path=f"{path}/start_month",
                message="当前任职开始月份晚于本批次基准月份",
                record_id=fact.id,
            )
        )
    return issues


def _time_warnings(dataset: Dataset) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            code="INCOMPLETE_EMPLOYMENT_TIME",
            path=f"/facts/{index}",
            message="任职时间不完整，可查询同公司，但不能凭此经历认定同期",
            record_id=fact.id,
        )
        for index, fact in enumerate(dataset.facts)
        if fact.active
        and fact.type == "employment"
        and (fact.start_month is None or (fact.end_month is None and not fact.is_current))
    ]


def _duplicate_fact_warnings(dataset: Dataset) -> list[ValidationIssue]:
    seen: dict[tuple[object, ...], str] = {}
    issues = []
    for index, fact in enumerate(dataset.facts):
        if not fact.active:
            continue
        key = (
            fact.person_id,
            fact.type,
            fact.entity_id,
            fact.role_id,
            fact.start_month,
            fact.end_month,
            fact.is_current,
        )
        if key in seen:
            issues.append(
                ValidationIssue(
                    code="POSSIBLE_DUPLICATE_FACT",
                    path=f"/facts/{index}",
                    message="经历内容相同，需核对是否来自独立证据；不会自动去重",
                    record_id=fact.id,
                    related_ids=[seen[key]],
                )
            )
        else:
            seen[key] = fact.id
    return issues


def _ambiguous_name_warnings(entities: list[Entity]) -> list[ValidationIssue]:
    names: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for index, entity in enumerate(entities):
        names[(entity.type, entity.name)][entity.id] = f"/entities/{index}/name"
        for alias_index, alias in enumerate(entity.aliases):
            names[(entity.type, alias)][entity.id] = f"/entities/{index}/aliases/{alias_index}"
    return [
        ValidationIssue(
            code="AMBIGUOUS_ENTITY_NAME",
            path=next(iter(owners.values())),
            message="同类型名称或别名对应多个实体，需由上游核对；不会自动合并",
            related_ids=sorted(owners),
        )
        for owners in names.values()
        if len(owners) > 1
    ]
