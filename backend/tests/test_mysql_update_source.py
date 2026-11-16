"""权威映射与MySQL协议边界回归，原生数据库／图链路由mysql_update_lab单独执行。"""

import copy
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pymysqlreplication.event import QueryEvent, XAPrepareEvent, XidEvent
from pymysqlreplication.row_event import DeleteRowsEvent, UpdateRowsEvent, WriteRowsEvent

from relationship_query.update.contract import SourceContract
from relationship_query.update.models import Cursor, SourceSnapshot, UpdateError
from relationship_query.update.mysql_source import MySQLSource, json_row
from relationship_query.update.projection import NumericProjectionAdapter

EXAMPLES = Path(__file__).resolve().parents[2] / "resources/examples"


@pytest.fixture
def authoritative():
    contract = SourceContract.model_validate_json(
        (EXAMPLES / "update-authoritative-contract-v1.json").read_text()
    )
    data = json.loads((EXAMPLES / "update-baseline-v1.json").read_text())
    del data["tables"]["mock.graph_expert_name_mapping"]
    for kind in ("company", "school", "major"):
        for row in data["tables"][f"mock.graph_{kind}_entity"]:
            row["uuid"] = f"test-{kind}-{row['id']}"
    return contract, SourceSnapshot.model_validate(data)


def test_authoritative_mapping_uses_source_rank_without_name_table(authoritative):
    contract, snapshot = authoritative
    plan = NumericProjectionAdapter(contract).build(contract.snapshot(snapshot.tables), 202611)
    assert len(plan.nodes) == 6 and {row["rank"] for row in plan.facts} == set(range(101, 107))
    assert "name_mapping" not in contract.tables


def test_authoritative_target_correction_keeps_upstream_id(authoritative):
    contract, snapshot = authoritative
    rows = contract.snapshot(snapshot.tables)
    rows["edge_mapping"][0]["standard_entity_id"] = 2
    plan = NumericProjectionAdapter(contract).build(rows, 202611)
    corrected = next(row for row in plan.facts if row["rank"] == 101)
    assert corrected["target"] == "e:company:2"


def test_authoritative_still_rejects_ambiguous_duplicate_slot(authoritative):
    contract, snapshot = authoritative
    rows = contract.snapshot(snapshot.tables)
    duplicate = {**rows["edge_mapping"][0], "id": 1001, "standard_entity_id": 2}
    rows["edge_mapping"].append(duplicate)
    with pytest.raises(UpdateError, match="槽位重复"):
        NumericProjectionAdapter(contract).build(rows, 202611)


def test_authoritative_v2_keeps_distinct_upstream_targets_and_ranks(authoritative):
    contract, snapshot = authoritative
    contract = contract.model_copy(update={"adapter": "numeric-authoritative-v2"})
    rows = contract.snapshot(snapshot.tables)
    rows["edge_mapping"].append({**rows["edge_mapping"][0], "id": 107, "standard_entity_id": 2})
    plan = NumericProjectionAdapter(contract).build(rows, 202611)
    selected = [edge for edge in plan.facts if edge["rank"] in (101, 107)]
    assert [(edge["rank"], edge["target"]) for edge in selected] == [
        (101, "e:company:1"),
        (107, "e:company:2"),
    ]
    assert selected[0]["properties"] == selected[1]["properties"]


def test_authoritative_v2_rejects_duplicate_target_fact(authoritative):
    contract, snapshot = authoritative
    contract = contract.model_copy(update={"adapter": "numeric-authoritative-v2"})
    rows = contract.snapshot(snapshot.tables)
    rows["edge_mapping"].append({**rows["edge_mapping"][0], "id": 107})
    with pytest.raises(UpdateError, match="槽位重复"):
        NumericProjectionAdapter(contract).build(rows, 202611)


def real_inputs(authoritative):
    from relationship_query.update.real_input import ENTITY_TABLES, PERSON_TABLES

    contract, snapshot = authoritative
    entities = {
        "tables": {
            name: snapshot.tables[contract.tables[logical].physical]
            for logical, name in ENTITY_TABLES.items()
        }
    }
    people = {
        "scope": "all-authoritative-mapping-references",
        "tables": {
            name: snapshot.tables[contract.tables[logical].physical]
            for logical, name in PERSON_TABLES.items()
        },
    }
    return contract, entities, people


def test_real_input_quarantines_missing_reference_without_rewriting_source(authoritative):
    from relationship_query.update.real_input import prepare_rows

    contract, entities, people = real_inputs(authoritative)
    entities["tables"]["graph_edge_mapping"][0]["source_person_id"] = 999
    rows, audit = prepare_rows(entities, people, contract)
    assert audit["quarantine"][0]["rank"] == 101
    assert audit["quarantine"][0]["reason"] == "MISSING_PERSON"
    assert 101 not in {row["id"] for row in rows["edge_mapping"]}
    assert len(entities["tables"]["graph_edge_mapping"]) == 6


def test_real_zero_date_becomes_unknown_and_preserves_original(authoritative):
    from relationship_query.update.real_input import prepare_rows

    contract, entities, people = real_inputs(authoritative)
    people["tables"]["experts_work_experience"][0]["start_date"] = "0000-00-00 00:00:00"
    rows, audit = prepare_rows(entities, people, contract)
    assert rows["work_expert"][0]["start_date"] is None
    assert len(audit["zero_dates_to_null"]) == 1
    assert people["tables"]["experts_work_experience"][0]["start_date"] == "0000-00-00 00:00:00"


def test_real_input_separates_deletion_from_bad_references(authoritative):
    from relationship_query.update.real_input import prepare_rows

    contract, entities, people = real_inputs(authoritative)
    people["tables"]["experts"][0]["deleted_at"] = "2026-11-01"
    rows, audit = prepare_rows(entities, people, contract)
    assert audit["quarantine"] == []
    projection = NumericProjectionAdapter(contract).build(rows, 202611)
    assert "p:expert:1" not in {node["vid"] for node in projection.nodes}
    assert not {101, 102, 103} & {edge["rank"] for edge in projection.facts}


def test_real_input_quarantines_incorrect_experience_owner(authoritative):
    from relationship_query.update.real_input import prepare_rows

    contract, entities, people = real_inputs(authoritative)
    people["tables"]["experts_work_experience"][0]["expert_id"] = 999
    rows, audit = prepare_rows(entities, people, contract)
    assert audit["quarantine"][0]["reason"] == "OWNER_MISMATCH"
    assert 101 not in {row["id"] for row in rows["edge_mapping"]}


@pytest.mark.parametrize(
    "end,reason",
    [
        ("1900-01-01", "REVERSED_INTERVAL"),
        ("2453-05-01", "DATE_OUT_OF_RANGE"),
    ],
)
def test_real_input_quarantines_unusable_intervals(authoritative, end, reason):
    from relationship_query.update.real_input import prepare_rows

    contract, entities, people = real_inputs(authoritative)
    people["tables"]["experts_work_experience"][0]["end_date"] = end
    rows, audit = prepare_rows(entities, people, contract)
    assert audit["quarantine"][0]["reason"] == reason
    assert 101 not in {row["id"] for row in rows["edge_mapping"]}


def test_unknown_work_status_does_not_create_current_end_date(authoritative):
    contract, snapshot = authoritative
    contract = contract.model_copy(update={"past_values": [0, 2]})
    rows = contract.snapshot(snapshot.tables)
    rows["work_expert"][0].update(is_employed=0, end_date=None)
    plan = NumericProjectionAdapter(contract).build(rows, 202611)
    edge = next(edge for edge in plan.facts if edge["rank"] == 101)
    assert edge["properties"]["is_current"] is False
    assert edge["properties"]["end_month"] is None


def test_authoritative_allows_retired_slot_and_its_active_replacement(authoritative):
    contract, snapshot = authoritative
    rows = contract.snapshot(snapshot.tables)
    rows["edge_mapping"][0]["deleted_at"] = "2026-11-01T00:00:00+00:00"
    replacement = {
        **rows["edge_mapping"][0],
        "id": 107,
        "standard_entity_id": 2,
        "deleted_at": None,
    }
    rows["edge_mapping"].append(replacement)
    plan = NumericProjectionAdapter(contract).build(rows, 202611)
    assert {row["rank"] for row in plan.facts} == {102, 103, 104, 105, 106, 107}


@pytest.mark.parametrize(
    "field,value", [("namespaces", {"x": {}}), ("matched_statuses", ["已匹配"])]
)
def test_authoritative_rejects_unused_name_configuration(authoritative, field, value):
    contract, _ = authoritative
    data = contract.model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        SourceContract.model_validate(data)


def test_json_row_preserves_bigint_and_dates():
    row = json_row(
        {
            "id": 9007199254740993,
            "time": datetime(2026, 11, 1, 0, 0, 0, 123456),
            "amount": Decimal("12.50"),
            "text": "虚构履历".encode(),
        }
    )
    assert row == {
        "id": 9007199254740993,
        "time": "2026-11-01T00:00:00.123456",
        "amount": "12.50",
        "text": "虚构履历",
    }


@pytest.fixture
def source(authoritative, monkeypatch):
    contract, _ = authoritative
    cursor = Cursor(
        source="mysql:test:mock", position={"file": "binlog.000001", "pos": 400, "schema": "s"}
    )
    result = MySQLSource({"database": "mock"}, contract, "test-generation", cursor=cursor)
    monkeypatch.setattr(result, "_check_resume", lambda: None)
    return result


def row_event(event_type, rows, *, table="experts", schema="mock", position=450):
    event = event_type.__new__(event_type)
    event.schema, event.table = schema, table
    event.packet = SimpleNamespace(log_pos=position)
    event._RowsEvent__rows = rows
    return event


@pytest.mark.parametrize(
    "event_type,values,operation",
    [
        (WriteRowsEvent, {"values": {"id": 1}}, "insert"),
        (UpdateRowsEvent, {"before_values": {"id": 1}, "after_values": {"id": 2}}, "update"),
        (DeleteRowsEvent, {"values": {"id": 1}}, "delete"),
    ],
)
def test_binlog_row_images_and_stable_event_ids(source, event_type, values, operation):
    event = row_event(event_type, [values])
    changes = source._changes(event, "binlog.000001")
    assert changes[0].operation == operation
    assert changes[0].event_id == "binlog.000001:450:0"
    assert changes[0].table == "mock.experts"


def test_binlog_filters_unconfigured_tables_before_core(source):
    event = row_event(WriteRowsEvent, [{"values": {"id": 1}}], table="graph_sync_batch")
    assert source._changes(event, "binlog.000001") == []


def install_stream(monkeypatch, events):
    class Stream:
        log_file = "binlog.000001"
        closed = False

        def __init__(self, **settings):
            self.settings = settings

        def __iter__(self):
            return iter(events)

        def close(self):
            Stream.closed = True

    monkeypatch.setattr("relationship_query.update.mysql_source.BinLogStreamReader", Stream)
    return Stream


def commit_event():
    event = XidEvent.__new__(XidEvent)
    event.packet = SimpleNamespace(log_pos=500)
    return event


def test_binlog_emits_only_complete_transaction_and_requires_ack(source, monkeypatch):
    stream = install_stream(
        monkeypatch, [row_event(WriteRowsEvent, [{"values": {"id": 1}}]), commit_event()]
    )
    iterator = source.transactions()
    transaction = next(iterator)
    assert transaction.previous == source.cursor and transaction.event_count == 1
    assert transaction.cursor.position["pos"] == 500
    with pytest.raises(UpdateError, match="确认后继续"):
        next(iterator)
    assert stream.closed and source.cursor.position["pos"] == 400


def test_binlog_ack_advances_after_delivery(source, monkeypatch):
    install_stream(monkeypatch, [commit_event()])
    iterator = source.transactions()
    transaction = next(iterator)
    source.acknowledge(transaction)
    assert list(iterator) == [] and source.cursor == transaction.cursor
    with pytest.raises(UpdateError, match="当前已交付"):
        source.acknowledge(transaction)


def test_partial_transaction_keeps_cursor_and_closes(source, monkeypatch):
    stream = install_stream(monkeypatch, [row_event(WriteRowsEvent, [{"values": {"id": 1}}])])
    with pytest.raises(UpdateError, match="未完成"):
        list(source.transactions())
    assert stream.closed and source.cursor.position["pos"] == 400


def test_transaction_budget_fails_before_ack(source, monkeypatch):
    source.max_events = 1
    install_stream(
        monkeypatch,
        [row_event(WriteRowsEvent, [{"values": {"id": 1}}, {"values": {"id": 2}}]), commit_event()],
    )
    with pytest.raises(UpdateError, match="预算"):
        list(source.transactions())
    assert source.cursor.position["pos"] == 400


def test_ddl_blocks_source(source, monkeypatch):
    event = QueryEvent.__new__(QueryEvent)
    event.schema, event.query = b"mock", "ALTER TABLE experts ADD unexpected INT"
    stream = install_stream(monkeypatch, [event])
    with pytest.raises(UpdateError, match="DDL"):
        list(source.transactions())
    assert stream.closed


def test_unsupported_xa_event_blocks_before_position_advance(source, monkeypatch):
    event = XAPrepareEvent.__new__(XAPrepareEvent)
    stream = install_stream(monkeypatch, [event])
    with pytest.raises(UpdateError, match="不支持"):
        list(source.transactions())
    assert stream.closed and source.cursor.position["pos"] == 400


def test_wrong_schema_and_unsafe_identifiers_rejected(authoritative):
    contract, _ = authoritative
    with pytest.raises(UpdateError, match="安全标识符"):
        MySQLSource({"database": "another"}, contract, "generation")
    broken = copy.deepcopy(contract.model_dump())
    broken["tables"]["company"]["physical"] = "mock.company;DROP"
    with pytest.raises(UpdateError, match="安全标识符"):
        MySQLSource({"database": "mock"}, SourceContract.model_validate(broken), "generation")
