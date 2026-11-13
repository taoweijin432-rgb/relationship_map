"""真实跨库输入的显式预检，保留原始快照及隔离记录。"""

from datetime import datetime
from typing import Any

from relationship_query.update.contract import SourceContract
from relationship_query.update.models import Row, UpdateError

ENTITY_TABLES = {
    "company": "graph_company_entity",
    "school": "graph_school_entity",
    "major": "graph_major_entity",
    "edge_mapping": "graph_edge_mapping",
}
PERSON_TABLES = {
    "person_expert": "experts",
    "work_expert": "experts_work_experience",
    "education_expert": "experts_education_experience",
    "person_resume": "resume",
    "work_resume": "resume_work_experience",
    "education_resume": "resume_education_experience",
}
ENTITY_KINDS = {"worked_at": "company", "studied_at": "school", "studied_major": "major"}


def prepare_rows(
    entities: dict[str, Any], people: dict[str, Any], contract: SourceContract
) -> tuple[dict[str, list[Row]], dict[str, Any]]:
    tables: dict[str, list[Row]] = {}
    zero_dates = []
    for logical, binding in contract.tables.items():
        source = entities if logical in ENTITY_TABLES else people
        name = (ENTITY_TABLES | PERSON_TABLES)[logical]
        records = []
        for original in source["tables"][name]:
            record = dict(original)
            for field in binding.datetime_fields:
                column = binding.columns[field]
                if record.get(column) == "0000-00-00 00:00:00":
                    record[column] = None
                    zero_dates.append({"table": name, "id": record["id"], "field": column})
            records.append(record)
        tables[binding.physical] = records
    rows = contract.snapshot(tables)
    indexes = {
        table: {int(str(row["id"])): row for row in records} for table, records in rows.items()
    }
    quarantine = []
    eligible = []
    for mapping in rows["edge_mapping"]:
        issue = mapping_issue(mapping, indexes, contract)
        if issue:
            quarantine.append(
                {
                    "rank": mapping["id"],
                    "source": mapping["source_system"],
                    "person_id": mapping["source_person_id"],
                    "table": mapping["source_table"],
                    "row_id": mapping["source_field_id"],
                    "reason": issue,
                }
            )
        else:
            eligible.append(mapping)
    audit = {
        "input_mapping_count": len(rows["edge_mapping"]),
        "quarantine": quarantine,
        "zero_dates_to_null": zero_dates,
        "scope": people["scope"],
        "separate_source_snapshots": True,
    }
    rows["edge_mapping"] = eligible
    return rows, audit


def mapping_issue(
    mapping: Row, indexes: dict[str, dict[int, Row]], contract: SourceContract
) -> str | None:
    if mapping["deleted_at"] is not None:
        return None
    binding = next(
        (
            entry
            for entry in contract.experiences
            if entry.source == mapping["source_system"]
            and entry.source_table_value == mapping["source_table"]
            and entry.fields.get(str(mapping["edge_type"])) == mapping["source_field"]
        ),
        None,
    )
    if binding is None:
        raise UpdateError("SLOT_MISMATCH", "真实映射与经历契约不一致")
    person = indexes[binding.person_table].get(int(str(mapping["source_person_id"])))
    raw = indexes[binding.table].get(int(str(mapping["source_field_id"])))
    target = indexes[ENTITY_KINDS[str(mapping["edge_type"])]].get(
        int(str(mapping["standard_entity_id"]))
    )
    if person is None:
        return "MISSING_PERSON"
    if raw is None:
        return "MISSING_EXPERIENCE"
    if target is None:
        return "MISSING_ENTITY"
    if raw["person_id"] != mapping["source_person_id"]:
        return "OWNER_MISMATCH"
    if any(row["deleted_at"] is not None for row in (person, raw, target)):
        return None
    start, end = raw["start_date"], raw["end_date"]
    dates = [datetime.fromisoformat(str(value)) for value in (start, end) if value is not None]
    if any(not 1900 <= value.year <= 2100 for value in dates):
        return "DATE_OUT_OF_RANGE"
    if (
        start is not None
        and end is not None
        and datetime.fromisoformat(str(start)) > datetime.fromisoformat(str(end))
    ):
        return "REVERSED_INTERVAL"
    return None
