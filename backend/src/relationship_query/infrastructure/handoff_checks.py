"""只对本轮新建实验库执行约束反例，全部在回滚事务内。"""

from typing import Any

from sqlalchemy import JSON, insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from relationship_query.infrastructure.handoff_schema import schema
from relationship_query.infrastructure.handoff_trial import MAPPING, identity
from relationship_query.infrastructure.mysql import lab_url


def constraint_checks(
    engine: Engine, rows: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    lab_url(engine.url.render_as_string(hide_password=False))
    company, mapping = rows["graph_company"][0], rows[MAPPING][0]
    definitions: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = [
        ("duplicate_company_code", "graph_company", company, {"entity_key": "negative.unique"}),
        ("item_zero", MAPPING, mapping, {"item_no": 0}),
        ("wrong_target_type", MAPPING, mapping, {"school_id": rows["graph_school"][0]["id"]}),
        ("matched_without_target", MAPPING, mapping, {"company_id": None}),
        ("unknown_entity", MAPPING, mapping, {"company_id": identity("missing")}),
        ("uuid_case_mismatch", MAPPING, mapping, {"company_id": company["id"].upper()}),
        ("bad_status", MAPPING, mapping, {"processing_status": "自动接受"}),
        ("bad_type", MAPPING, mapping, {"entity_type": "role"}),
        ("bad_deleted", MAPPING, mapping, {"is_deleted": 2}),
        ("missing_batch", MAPPING, mapping, {"sync_batch_id": 999}),
        ("string_parent", "graph_company", company, {"parent_company_codes": "C001"}),
        ("json_null_parent", "graph_company", company, {"parent_company_codes": JSON.NULL}),
        ("object_aliases", "graph_company", company, {"former_names": {"old": "name"}}),
        ("bad_sync_mode", "graph_sync_batch", rows["graph_sync_batch"][0], {"sync_mode": "other"}),
        (
            "self_relation",
            "graph_company_relation",
            rows["graph_company_relation"][0],
            {"child_company_id": company["id"]},
        ),
        (
            "bad_relation",
            "graph_company_relation",
            rows["graph_company_relation"][0],
            {"relation_type": "投资"},
        ),
    ]
    results = []
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            for name, table, base, changes in definitions:
                value = {**base, "id": 99 if table == "graph_sync_batch" else identity(name)}
                if table == "graph_company" and name != "duplicate_company_code":
                    value.update(company_code="N_" + name, entity_key="negative." + name)
                value.update(changes)
                savepoint = connection.begin_nested()
                code = None
                try:
                    connection.execute(insert(schema.tables[table]), value)
                except (IntegrityError, OperationalError) as exc:
                    code = exc.orig.args[0] if exc.orig else None
                    if code not in {1062, 1452, 3819}:
                        raise
                finally:
                    savepoint.rollback()
                expected = (
                    1062
                    if name == "duplicate_company_code"
                    else (
                        1452
                        if name in {"unknown_entity", "uuid_case_mismatch", "missing_batch"}
                        else 3819
                    )
                )
                results.append(
                    dict(
                        case=name,
                        rejected=code == expected,
                        mysql_code=code,
                        expected_code=expected,
                    )
                )
        finally:
            transaction.rollback()
    return results
