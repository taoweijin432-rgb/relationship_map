"""新版数字来源适配。只生成允许入图的事实，人物关系继续由nGQL计算。"""

from datetime import datetime, timezone
from typing import Literal, cast

from relationship_query.domain.models import Fact
from relationship_query.update.contract import AUTHORITATIVE_ADAPTERS, SourceContract
from relationship_query.update.models import Projection, Row, UpdateError

ENTITY_KIND = {"worked_at": "company", "studied_at": "school", "studied_major": "major"}
FACT_KIND = {"worked_at": "employment", "studied_at": "education", "studied_major": "major"}


def positive_id(value: object) -> int:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 0 < value < 2**63:
        raise UpdateError("INVALID_BIGINT", "来源标识必须为正有符号64位整数")
    return value


def text(value: object, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or (not value and not nullable):
        raise UpdateError("INVALID_TEXT", "必需文本缺失或字段类型变化")
    return value


def timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise UpdateError("INVALID_DATE", "时间字段需要ISO日期或明确NULL")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise UpdateError("INVALID_DATE", "时间字段格式变化") from None
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def month(value: datetime | None) -> int | None:
    return value.year * 100 + value.month if value is not None else None


def accepted_status(value: object, active: list[str], inactive: list[str]) -> bool:
    status = text(value)
    if status in active:
        return True
    if status in inactive:
        return False
    raise UpdateError("STATUS_MAPPING_REQUIRED", "来源出现未配置的状态值，请核对契约")


class NumericProjectionAdapter:
    def __init__(self, contract: SourceContract) -> None:
        self.contract = contract
        required = {
            kind: {"id", "name", "code", "verification_status", "deleted_at"}
            for kind in ("company", "school", "major")
        }
        required.update(
            {
                name: {"id", "name", "serial_number", "deleted_at"}
                for name in contract.people.values()
            }
        )
        required["edge_mapping"] = {
            "id",
            "source_system",
            "source_table",
            "source_field_id",
            "source_field",
            "source_person_id",
            "standard_entity_id",
            "edge_type",
            "deleted_at",
        }
        if contract.adapter == "numeric-v1":
            required["name_mapping"] = {
                "id",
                "entity_type",
                "source_namespace",
                "source_field_id",
                "company_id",
                "school_id",
                "major_id",
                "processing_status",
            }
        for binding in contract.experiences:
            fields = {"id", "person_id", "start_date", "end_date", "deleted_at"}
            if "worked_at" in binding.fields:
                fields |= {"position_title", "is_employed"}
                if set(binding.fields) != {"worked_at"}:
                    raise UpdateError("INVALID_CONTRACT", "工作与教育字段不能绑定到同条经历")
            else:
                fields |= {"education_level", "is_regular_enrollment"}
            required[binding.table] = fields
        for table, columns in required.items():
            if table not in contract.tables or not columns.issubset(contract.tables[table].columns):
                raise UpdateError("INVALID_CONTRACT", f"逻辑表 {table} 的必需字段映射不完整")
        self.slots = {
            (entry.source, entry.source_table_value, kind): entry
            for entry in contract.experiences
            for kind in entry.fields
        }
        if len(self.slots) != sum(len(entry.fields) for entry in contract.experiences):
            raise UpdateError("INVALID_CONTRACT", "经历槽位配置重复")

    def build(self, rows: dict[str, list[Row]], reference_month: int) -> Projection:
        indexed = {
            table: {positive_id(row["id"]): row for row in records}
            for table, records in rows.items()
        }
        if any(len(indexed[name]) != len(records) for name, records in rows.items()):
            raise UpdateError("DUPLICATE_KEY", "数字来源主键重复")
        nodes = self._nodes(indexed)
        names = (
            self._name_targets(rows["name_mapping"])
            if self.contract.adapter == "numeric-v1"
            else None
        )
        slots: set[tuple[object, ...]] = set()
        facts: list[Row] = []
        for mapping in rows["edge_mapping"]:
            if (
                self.contract.adapter in AUTHORITATIVE_ADAPTERS
                and timestamp(mapping["deleted_at"]) is not None
            ):
                continue
            key = tuple(
                mapping[field]
                for field in (
                    "source_system",
                    "source_table",
                    "source_field_id",
                    "source_field",
                )
            )
            if self.contract.adapter == "numeric-authoritative-v2":
                # 上游每个目标事实各有Rank，同一原文字段可关联多个已确认实体。
                key += (mapping["standard_entity_id"],)
            if key in slots:
                raise UpdateError("DUPLICATE_SLOT", "来源经历字段槽位重复")
            slots.add(key)
            fact = self._fact(mapping, indexed, names, reference_month)
            if fact is not None:
                facts.append(fact)
        return Projection(
            nodes=sorted(nodes, key=lambda node: str(node["vid"])),
            facts=sorted(facts, key=lambda edge: int(str(edge["rank"]))),
        )

    def _nodes(self, rows: dict[str, dict[int, Row]]) -> list[Row]:
        nodes: list[Row] = []
        for kind in ("company", "school", "major"):
            for identity, row in rows[kind].items():
                if timestamp(row["deleted_at"]) is not None or not self._entity_active(row, kind):
                    continue
                nodes.append(
                    {
                        "vid": f"e:{kind}:{identity}",
                        "type": kind,
                        "properties": {
                            "name": text(row["name"]),
                            f"{kind}_code": text(row["code"]),
                        },
                    }
                )
        for source, table in self.contract.people.items():
            serials: set[str | None] = set()
            for identity, row in rows[table].items():
                text(row["name"])
                serial = text(row["serial_number"])
                if serial in serials:
                    raise UpdateError("DUPLICATE_SERIAL", "同来源业务编号重复")
                serials.add(serial)
                if timestamp(row["deleted_at"]) is None:
                    nodes.append(
                        {
                            "vid": f"p:{source}:{identity}",
                            "type": "person",
                            "properties": {"source_system": source, "serial_number": serial},
                        }
                    )
        return nodes

    def _name_targets(self, rows: list[Row]) -> dict[tuple[str, int, str], set[int]]:
        targets: dict[tuple[str, int, str], set[int]] = {}
        for row in rows:
            rule = self.contract.namespaces.get(str(row["source_namespace"]))
            if rule is None:
                continue
            if not accepted_status(
                row["processing_status"],
                self.contract.matched_statuses,
                self.contract.unmatched_statuses,
            ):
                continue
            if row["entity_type"] != rule.entity_type:
                raise UpdateError("NAMESPACE_TYPE", "名称映射类别与显式命名空间不符")
            source_key = str(row["source_field_id"])
            if not source_key.startswith(rule.id_prefix):
                raise UpdateError("NAMESPACE_KEY", "名称映射来源键与显式前缀不符")
            identity = positive_id(source_key[len(rule.id_prefix) :])
            target = positive_id(row[rule.entity_type + "_id"])
            key = rule.experience_table, identity, rule.entity_type
            targets.setdefault(key, set()).add(target)
        return targets

    def _entity_active(self, row: Row, kind: str) -> bool:
        return accepted_status(
            row["verification_status"],
            self.contract.entity_statuses[kind],
            self.contract.inactive_entity_statuses.get(kind, []),
        )

    def _fact(
        self,
        mapping: Row,
        rows: dict[str, dict[int, Row]],
        names: dict[tuple[str, int, str], set[int]] | None,
        reference_month: int,
    ) -> Row | None:
        rank = positive_id(mapping["id"])
        if timestamp(mapping["deleted_at"]) is not None:
            return None
        source, kind = str(mapping["source_system"]), str(mapping["edge_type"])
        binding = self.slots.get((source, str(mapping["source_table"]), kind))
        if binding is None or binding.fields[kind] != mapping["source_field"]:
            raise UpdateError("SLOT_MISMATCH", "事实槽位与来源契约不符")
        raw_id, person_id = (
            positive_id(mapping["source_field_id"]),
            positive_id(mapping["source_person_id"]),
        )
        entity_type = ENTITY_KIND[kind]
        target_id = positive_id(mapping["standard_entity_id"])
        raw = rows[binding.table].get(raw_id)
        person = rows[binding.person_table].get(person_id)
        target = rows[entity_type].get(target_id)
        if (
            raw is None
            or person is None
            or target is None
            or positive_id(raw["person_id"]) != person_id
        ):
            raise UpdateError("SOURCE_REFERENCE", "事实来源、归属或实体引用不完整")
        targets = (
            names.get((binding.table, raw_id, entity_type), set()) if names is not None else None
        )
        if (
            targets == set()
            or timestamp(raw["deleted_at"]) is not None
            or timestamp(person["deleted_at"]) is not None
            or timestamp(target["deleted_at"]) is not None
            or not self._entity_active(target, entity_type)
        ):
            return None
        if targets is not None and targets != {target_id}:
            raise UpdateError("NAME_MAPPING_MISMATCH", "名称归一目标与事实槽位不一致或存在多目标")
        return self._experience_fact(mapping, raw, source, kind, entity_type, rank, reference_month)

    def _experience_fact(
        self,
        mapping: Row,
        raw: Row,
        source: str,
        kind: str,
        entity_type: str,
        rank: int,
        reference_month: int,
    ) -> Row:
        start, end = timestamp(raw["start_date"]), timestamp(raw["end_date"])
        if start is not None and end is not None and start > end:
            raise UpdateError("INVALID_INTERVAL", "经历日期区间倒置")
        work = kind == "worked_at"
        current = False
        if work:
            status = raw["is_employed"]
            if (
                type(status) is not int
                or status not in self.contract.current_values + self.contract.past_values
            ):
                raise UpdateError("CURRENT_STATUS", "在职状态需要明确映射")
            current = status in self.contract.current_values
        person_id = f"p:{source}:{positive_id(mapping['source_person_id'])}"
        target = f"e:{entity_type}:{positive_id(mapping['standard_entity_id'])}"
        fact = Fact(
            id=f"slot:{rank}",
            person_id=person_id,
            type=cast(Literal["employment", "education", "major"], FACT_KIND[kind]),
            entity_id=target,
            start_month=month(start),
            end_month=month(end),
            is_current=current,
            source_system=cast(Literal["expert", "resume"], source),
            source_record_id=f"{mapping['source_table']}:{raw['id']}",
        )
        if current and fact.start_month is not None and fact.start_month > reference_month:
            raise UpdateError("FUTURE_CURRENT", "在职开始月份晚于基准月")
        properties: Row = {
            "experience_key": f"{source}:{mapping['source_table']}:{raw['id']}",
            "start_month": fact.start_month,
            "end_month": fact.end_month,
        }
        if work:
            properties.update(
                is_current=current, position_title=text(raw["position_title"], nullable=True)
            )
        else:
            properties.update(
                education_level=text(raw["education_level"], nullable=True),
                is_regular_enrollment=text(raw["is_regular_enrollment"], nullable=True),
            )
        return {
            "source": person_id,
            "target": target,
            "type": kind,
            "rank": rank,
            "properties": properties,
        }
