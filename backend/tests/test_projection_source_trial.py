"""三表／原表的槽位语义；与当前 API 图格式分开验证。"""

import os
from datetime import datetime

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import DBAPIError

from relationship_query.infrastructure.handoff_trial import make_fixture
from relationship_query.infrastructure.projection_source_schema import (
    ALIAS,
    ENTITY,
    MAPPING,
    schema,
)
from relationship_query.infrastructure.projection_source_trial import (
    clean_name,
    make_projection_rows,
    open_projection_engine,
    projection_records,
)
from tests.test_mysql import new_lab


def fixture():
    source, raw = make_fixture("a" * 64)
    return make_projection_rows(source, raw)


def primary(rows):
    return next(
        m
        for m in rows[MAPPING]
        if m["source_system"] == "expert"
        and m["source_table"] == "experts_work_experience"
        and m["source_field_id"] == 1
        and m["source_field"] == "company_name"
    )


def test_document_vid_slot_identity_and_upstream_bridge():
    rows, bridge = fixture()
    nodes, edges = projection_records(rows)
    assert len(bridge) == 15 and len(nodes) == 84 and len(edges) == 246
    assert len(rows[MAPPING]) == len({m["id"] for m in rows[MAPPING]}) == 252
    assert {"p:expert:13", "p:resume:13"}.issubset({n["vid"] for n in nodes})
    assert {e["type"] for e in edges} == {
        "worked_at",
        "held_role",
        "studied_at",
        "studied_major",
        "participated_in",
        "collaborated with",
    }
    assert all(e["rank"] > 0 and e["properties"]["fact_id"] == f"slot:{e['rank']}" for e in edges)
    assert all(
        e["properties"]["start_date"] is None or e["properties"]["start_date"] >= 190001
        for e in edges
    )
    # 同名实体确实存在；原记录的上游 UUID 决定目标，不按名称任意择优。
    target = next(e for e in rows[ENTITY] if e["id"] == primary(rows)["entity_id"])
    assert len([e for e in rows[ENTITY] if e["canonical_name"] == target["canonical_name"]]) == 2
    assert clean_name("　Ａ公司 ") == "A公司"


@pytest.mark.parametrize(
    "problem,code",
    [
        ("missing_raw", "SOURCE_MISSING_OR_DELETED"),
        ("owner", "SOURCE_PERSON_MISMATCH"),
        ("raw_owner_null", "SOURCE_PERSON_MISMATCH"),
        ("wrong_entity", "ENTITY_TYPE_OR_STATE"),
        ("stale_name", "STALE_OR_UNCONFIRMED_NAME"),
        ("current_with_end", "INVALID_DATE_STATE"),
        ("inverted", "INVALID_DATE_STATE"),
        ("employment_state", "UNKNOWN_EMPLOYED_STATE"),
        ("missing_slot", "UNMAPPED_SLOT"),
        ("duplicate_slot", "DUPLICATE_SLOT"),
        ("negative_rank", "INVALID_RANK"),
        ("overflow_rank", "INVALID_RANK"),
        ("out_of_range_date", "月份必须"),
    ],
)
def test_no_guessing_or_partial_source_slot_publication(problem, code):
    rows, _ = fixture()
    slot = primary(rows)
    raw = next(r for r in rows["experts_work_experience"] if r["id"] == 1)
    if problem == "missing_raw":
        rows["experts_work_experience"].remove(raw)
    elif problem == "owner":
        slot["source_person_id"] = 5
    elif problem == "raw_owner_null":
        raw["expert_id"] = None
    elif problem == "wrong_entity":
        slot["entity_id"] = next(e["id"] for e in rows[ENTITY] if e["entity_type"] == "role")
    elif problem == "stale_name":
        raw["company_name"] = "未归一的新原文"
    elif problem == "current_with_end":
        raw["is_employed"] = 1
    elif problem == "inverted":
        raw["start_date"] = datetime(2023, 1, 1)
    elif problem == "employment_state":
        raw["is_employed"] = 3
    elif problem == "missing_slot":
        rows[MAPPING].remove(slot)
    elif problem == "negative_rank":
        slot["id"] = -1
    elif problem == "overflow_rank":
        slot["id"] = 2**63
    elif problem == "out_of_range_date":
        raw["start_date"] = datetime(1899, 1, 1)
    else:
        rows[MAPPING].append({**slot, "id": 9999})
    with pytest.raises(ValueError, match=code):
        projection_records(rows)


def test_person_move_target_correction_and_rename_keep_rank():
    rows, _ = fixture()
    _, before = projection_records(rows)
    slot = primary(rows)
    original_rank = slot["id"]
    other = next(
        m
        for m in rows[MAPPING]
        if m["source_system"] == "resume"
        and m["source_person_id"] == 8
        and m["edge_type"] == "worked_at"
    )
    target = next(e for e in rows[ENTITY] if e["id"] == other["entity_id"])
    raw = next(r for r in rows["experts_work_experience"] if r["id"] == 1)
    raw.update(expert_id=5, company_name=target["canonical_name"])
    for item in rows[MAPPING]:
        if item["source_table"] == "experts_work_experience" and item["source_field_id"] == 1:
            item["source_person_id"] = 5
    slot["entity_id"] = target["id"]
    target["canonical_name"] += "（更名）"
    _, after = projection_records(rows)
    a = next(e for e in before if e["rank"] == original_rank)
    b = next(e for e in after if e["rank"] == original_rank)
    assert b["source"] == "p:expert:5" and b["target"] == f"e:{target['id']}"
    assert (a["source"], a["target"]) != (b["source"], b["target"])
    assert len(after) == len(before)


@pytest.mark.skipif(
    os.environ.get("RELATIONSHIP_MYSQL_TEST") != "1", reason="显式启用三表 MySQL 约束验收"
)
def test_live_three_table_primary_rank_and_polymorphic_slot_constraints():
    rows, _ = fixture()
    with new_lab() as url:
        engine = open_projection_engine(url, writable=True)
        try:
            schema.create_all(engine)
            with engine.begin() as connection:
                for table in schema.sorted_tables:
                    connection.execute(insert(table), rows[table.name])
            base = primary(rows)
            probes = [
                ({"id": 9998, "source_field_id": 901, "entity_id": 99999}, 1452),
                ({"id": 9999}, 1062),
                ({"id": 9999, "source_field_id": 900, "edge_type": "held_role"}, 3819),
                ({"id": 9999, "source_field_id": 900, "entity_id": 99999}, 1452),
                ({"id": -1, "source_field_id": 900}, 3819),
                ({"id": 2**63, "source_field_id": 900}, 1264),
            ]
            with engine.begin() as connection:
                for index, (changes, expected) in enumerate(probes):
                    if changes["id"] == 9999:
                        changes = {**changes, "id": 9999 + index}
                    savepoint = connection.begin_nested()
                    code = None
                    try:
                        connection.execute(insert(schema.tables[MAPPING]), {**base, **changes})
                    except DBAPIError as error:
                        code = error.orig.args[0]
                    finally:
                        savepoint.rollback()
                    assert code == expected, (changes, code, expected)
            assert len(schema.tables[ALIAS].columns) == 6
            assert len(schema.tables[ENTITY].columns) == 6
            assert len(schema.tables[MAPPING].columns) == 11
        finally:
            engine.dispose()
