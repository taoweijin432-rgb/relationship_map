"""新设计六表：物理约束与原经历关联分别验证，不修改真实来源。"""

import copy
import json
import os
from collections import Counter

import pytest
from sqlalchemy import insert, inspect, select

from relationship_query.contracts import SearchRequest
from relationship_query.infrastructure.handoff_checks import constraint_checks
from relationship_query.infrastructure.handoff_schema import ddl, schema
from relationship_query.infrastructure.handoff_trial import (
    MAPPING,
    STAMP,
    _raw_id,
    convert_tables,
    identity,
    make_fixture,
)
from relationship_query.infrastructure.mysql import open_mysql_engine
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.infrastructure.sqlite import load_dataset, open_engine
from relationship_query.services.query import QueryService
from tests.test_mysql import new_lab


def fixture():
    return make_fixture("a" * 64)


def test_six_tables_match_document_shape_and_constraints():
    assert set(schema.tables) == {
        "graph_sync_batch",
        "graph_company",
        "graph_school",
        "graph_major",
        "graph_company_relation",
        MAPPING,
    }
    assert len(schema.tables[MAPPING].columns) == 14
    sql = ddl()
    for phrase in ("ascii_bin", "utf8mb4_bin", "DATETIME(6)", "item_no > 0", "InnoDB"):
        assert phrase in sql
    assert "CASCADE" not in sql and "DROP " not in sql
    assert "Relationship_Graph_edge_mapping" not in sql


def test_fixture_reproducible_readonly_and_namespace_aware():
    rows, raw = fixture()
    before = copy.deepcopy((rows, raw))
    dataset, trace, issues = convert_tables(rows, raw)
    assert (rows, raw) == before == fixture()
    assert len(dataset.people) == 60 and len(dataset.facts) == len(trace) == 122
    assert len({f.source_record_id for f in dataset.facts}) == 122
    assert (
        len({r["source_namespace"] for r in raw["experiences"] if r["source_record_id"] == "1"})
        == 4
    )
    assert _raw_id(("a:b", "c")) != _raw_id(("a", "b:c"))
    assert all(f.source_record_id.startswith("mock-raw:") for f in dataset.facts)
    assert all(e.type != "major" for e in dataset.entities)
    assert Counter(i["code"] for i in issues) == {
        "MAJOR_NOT_A_ROLE_OR_SCHOOL": 60,
        "MAPPING_NOT_CONSUMED": 6,
    }
    assert sum(p["duplicate_mappings_collapsed"] for p in trace) == 1


@pytest.mark.parametrize(
    "problem,code",
    [
        ("multi_target", "归一目标缺失或不唯一"),
        ("deleted_target", "MAPPING_TARGET_MISSING_OR_DELETED"),
        ("missing_raw", "RAW_EXPERIENCE_NOT_FOUND"),
        ("stale_name", "STALE_RAW_NAME"),
        ("bad_namespace", "RAW_EXPERIENCE_NOT_FOUND"),
        ("duplicate_raw", "DUPLICATE_RAW_EXPERIENCE"),
        ("bad_parent", "UNKNOWN_OR_DUPLICATE_COMPANY_CODE"),
        ("unpublished", "UNPUBLISHED_BATCH"),
        ("wrong_kind", "归一实体类型错误"),
    ],
)
def test_logical_errors_are_locatable_without_guessing(problem, code):
    rows, raw = fixture()
    first = rows[MAPPING][0]
    if problem == "multi_target":
        rows[MAPPING].append(
            {**first, "id": identity("split"), "item_no": 3, "company_id": identity("company:1")}
        )
    elif problem == "deleted_target":
        next(r for r in rows["graph_company"] if r["id"] == first["company_id"])["is_deleted"] = 1
        for company in rows["graph_company"]:
            company.update(parent_company_codes=0, child_company_codes=0)
    elif problem == "missing_raw":
        first["source_record_id"] = "missing"
    elif problem == "stale_name":
        first["raw_name"] = "旧版本原文"
    elif problem == "bad_namespace":
        first["source_namespace"] = "unknown"
    elif problem == "duplicate_raw":
        raw["experiences"].append(raw["experiences"][0])
    elif problem == "bad_parent":
        rows["graph_company"][0]["child_company_codes"] = ["UNKNOWN"]
    elif problem == "unpublished":
        rows["graph_sync_batch"][0]["status"] = "loading"
    else:
        # 同一来源条目仍不能把学校当作任职组织，item_no 不提供跨类别配对语义。
        for mapping in rows[MAPPING]:
            if (mapping["source_namespace"], mapping["source_record_id"]) == (
                first["source_namespace"],
                first["source_record_id"],
            ):
                mapping.update(
                    entity_type="school", company_id=None, school_id=identity("school:0")
                )
    with pytest.raises(ValueError, match=code):
        convert_tables(rows, raw)


def test_corrections_and_soft_delete_change_facts_without_person_inference(tmp_path):
    rows, raw = fixture()
    original, _, _ = convert_tables(rows, raw)
    person_two = next(r for r in raw["experiences"] if r["fact_id"] == "trial:f:000002:work")
    selected = [
        m
        for m in rows[MAPPING]
        if m["entity_type"] == "company"
        and (m["source_namespace"], m["source_record_id"])
        == (person_two["source_namespace"], person_two["source_record_id"])
    ]
    for mapping in selected:
        mapping["company_id"] = identity("company:1")
    changed, _, _ = convert_tables(rows, raw)
    assert [p.id for p in original.people] == [p.id for p in changed.people]
    for label, data, expected in (("before", original, True), ("after", changed, False)):
        engine = open_engine(tmp_path / f"{label}.sqlite")
        try:
            load_dataset(engine, data)
            proofs = QueryService(SQLRepository(engine)).evidence("p:000001", "p:000002").items
            assert any(p.relation_type == "same_company_overlap" for p in proofs) == expected
        finally:
            engine.dispose()
    for mapping in selected:
        mapping["is_deleted"] = 1
    deleted, _, issues = convert_tables(rows, raw)
    assert not any(f.id == "trial:f:000002:work" for f in deleted.facts)
    assert any(i["code"] == "RAW_WITHOUT_PUBLISHED_MAPPING" for i in issues)


def test_company_hierarchy_does_not_create_same_company_relationship(tmp_path):
    rows, raw = fixture()
    rows["graph_company_relation"] = []
    _, _, issues = convert_tables(rows, raw)
    assert any(i["code"] == "COMPANY_RELATION_MISMATCH" for i in issues)
    rows, raw = fixture()
    dataset, _, _ = convert_tables(rows, raw)
    engine = open_engine(tmp_path / "query.sqlite")
    try:
        load_dataset(engine, dataset)
        service = QueryService(SQLRepository(engine))
        proofs = service.evidence("p:000001", "p:000008").items
        assert not any(p.relation_type != "same_school" for p in proofs)
        result = service.search(
            SearchRequest(
                organization_ids=[raw["slots"]["org:0"]],
                role_ids=["role:0"],
            )
        )
        assert [p.person.id for p in result.items] == ["p:000001", "p:000031"]
    finally:
        engine.dispose()


@pytest.mark.skipif(
    os.environ.get("RELATIONSHIP_MYSQL_TEST") != "1", reason="显式启用本机 MySQL 六表验收"
)
def test_live_mysql_constraints_collations_and_roundtrip():
    rows, raw = fixture()
    expected, _, _ = convert_tables(rows, raw)
    with new_lab() as url:
        engine = open_mysql_engine(url, writable=True)
        try:
            schema.create_all(engine)
            with engine.begin() as connection:
                for table in schema.sorted_tables:
                    connection.execute(insert(table), rows[table.name])
            checks = constraint_checks(engine, rows)
            assert len(checks) == 16 and all(c["rejected"] for c in checks), checks
            with engine.connect() as connection:
                actual = {
                    t.name: [dict(r) for r in connection.execute(select(t)).mappings()]
                    for t in schema.sorted_tables
                }
                types = (
                    connection.exec_driver_sql(
                        "SELECT COLUMN_NAME,COLLATION_NAME,DATETIME_PRECISION "
                        "FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='graph_company'"
                    )
                    .mappings()
                    .all()
                )
            by_name = {r["COLUMN_NAME"]: r for r in types}
            assert by_name["id"]["COLLATION_NAME"] == "ascii_bin"
            assert by_name["standard_name"]["COLLATION_NAME"] == "utf8mb4_bin"
            assert by_name["source_updated_at"]["DATETIME_PRECISION"] == 6
            assert actual["graph_company"][0]["source_updated_at"] == STAMP
            assert {json.dumps(r["child_company_codes"]) for r in actual["graph_company"]} == {
                "null",
                "0",
                '["C001"]',
            }
            data, _, _ = convert_tables(actual, raw)
            assert sorted(data.facts, key=lambda f: f.id) == sorted(
                expected.facts, key=lambda f: f.id
            )
            assert set(inspect(engine).get_table_names()) == set(schema.tables)
        finally:
            engine.dispose()
