"""独立小样例：事实入图后由 nGQL 计算并写入人物边，不改已有空间或服务。"""

import argparse
import hashlib
import json
import secrets
from collections import Counter
from pathlib import Path
from typing import Any

from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
    require_space,
)
from verify_graph_ddl import (
    COMPANY_A,
    COMPANY_B,
    MAJOR,
    ROOT,
    SCHEMA,
    SCHOOL,
    create_fixture,
    expect_rows,
    schema_statements,
    verify_business_information,
    verify_person_privacy,
)

EXTENSION = ROOT / "infra/nebula/schema/person-relations-v3.ngql"
MODEL = "uuid-relations-v5"
EXPECTED = ROOT / "docs/examples/person-relations-v3-expected.json"
RELATION_SOURCES = {
    "same_company": ("worked_at", "company", (COMPANY_A, COMPANY_B)),
    "company_overlap": ("worked_at", "company", (COMPANY_A, COMPANY_B)),
    "same_school": ("studied_at", "school", (SCHOOL,)),
    "same_major": ("studied_major", "major", (MAJOR,)),
}


class RelationBudgetExceeded(RuntimeError):
    """样例预算耗尽，不允许将部分关系发布为完整图。"""


def extension_statements() -> list[str]:
    text = "\n".join(
        line for line in EXTENSION.read_text().splitlines() if not line.lstrip().startswith("--")
    )
    statements = [part.strip() for part in text.split(";") if part.strip()]
    if not all(part.startswith("CREATE EDGE ") for part in statements):
        raise ValueError("本工具只读取固定人物边 DDL")
    return statements


def calculation_query(kind: str, entity: str, limit: int) -> str:
    fact, tag, _ = RELATION_SOURCES[kind]
    statement = (
        f"MATCH (a:person)-[l:{fact}]->(e:{tag})<-[r:{fact}]-(b:person) "
        f"WHERE id(e)=={json.dumps(entity)} AND id(a)<id(b) "
    )
    columns = (
        "id(a) AS source, id(b) AS target, id(e) AS entity_vid, "
        "rank(l) AS left_fact_rank, rank(r) AS right_fact_rank"
    )
    if kind == "company_overlap":
        statement += (
            "WITH a,b,e,l,r, "
            "CASE WHEN l.is_current THEN 202611 ELSE l.end_month END AS le, "
            "CASE WHEN r.is_current THEN 202611 ELSE r.end_month END AS re "
            "WHERE l.start_month IS NOT NULL AND r.start_month IS NOT NULL "
            "AND le IS NOT NULL AND re IS NOT NULL "
            "AND l.start_month<=le AND r.start_month<=re "
            "AND l.start_month<=re AND r.start_month<=le "
        )
        columns += (
            ", CASE WHEN l.start_month>=r.start_month THEN l.start_month "
            "ELSE r.start_month END AS overlap_start_month, "
            "CASE WHEN le<=re THEN le ELSE re END AS overlap_end_month"
        )
    return (
        statement
        + "RETURN DISTINCT "
        + columns
        + (f" ORDER BY source,target,entity_vid,left_fact_rank,right_fact_rank LIMIT {limit}")
    )


def calculate(session: Any, budget: int) -> list[dict[str, Any]]:
    """图计算规则；Python 只分配当前快照的局部 Rank，不重算时间或关系。"""
    results: list[dict[str, Any]] = []
    for kind, (_, _, entities) in RELATION_SOURCES.items():
        for entity in entities:
            rows = query(session, calculation_query(kind, entity, budget - len(results) + 1))
            if len(results) + len(rows) > budget:
                raise RelationBudgetExceeded("小样例计算预算耗尽，未写人物边")
            results.extend({"kind": kind, **row} for row in rows)
    results.sort(
        key=lambda r: (
            r["kind"],
            r["source"],
            r["target"],
            r["entity_vid"],
            r["left_fact_rank"],
            r["right_fact_rank"],
        )
    )
    counters: Counter[tuple[str, str, str]] = Counter()
    for row in results:
        key = row["kind"], row["source"], row["target"]
        counters[key] += 1
        row["rank"] = counters[key]
    return results


def insert_relations(session: Any, rows: list[dict[str, Any]]) -> None:
    for kind in RELATION_SOURCES:
        fields = ["entity_vid", "left_fact_rank", "right_fact_rank"]
        if kind == "company_overlap":
            fields += ["overlap_start_month", "overlap_end_month"]
        selected = [row for row in rows if row["kind"] == kind]
        if not selected:
            continue
        values = []
        for row in selected:
            properties = ",".join(json.dumps(row[field]) for field in fields)
            values.append(
                f"{json.dumps(row['source'])}->{json.dumps(row['target'])}"
                f"@{row['rank']}:({properties})"
            )
        query(
            session, f"INSERT EDGE {kind}({','.join(fields)}) VALUES " + ",".join(values), wait=True
        )


def check_relations(session: Any, checks: list[dict[str, Any]], *, corrected: bool) -> None:
    pair = (
        "MATCH (a:person)-[r:same_company]-(b:person) "
        'WHERE id(a)=="p:expert:101" AND id(b)=="p:resume:102" '
        "RETURN r.left_fact_rank AS left_rank, r.right_fact_rank AS right_rank "
        "ORDER BY left_rank,right_rank LIMIT 100"
    )
    expected = [{"left_rank": 7002, "right_rank": 7003}]
    if not corrected:
        expected.insert(0, {"left_rank": 7001, "right_rank": 7003})
    expect_rows(session, checks, "双方经历引用与重复任职", pair, expected)
    overlap = (
        "MATCH (a:person)-[r:company_overlap]-(b:person) "
        'WHERE id(a)=="p:resume:102" AND id(b)=="p:expert:101" '
        "RETURN r.left_fact_rank AS left_rank, r.right_fact_rank AS right_rank, "
        "r.overlap_start_month AS start_month,r.overlap_end_month AS end_month LIMIT 100"
    )
    expect_rows(
        session,
        checks,
        "反向读取仍保持原证据归属与交集",
        overlap,
        []
        if corrected
        else [{"left_rank": 7001, "right_rank": 7003, "start_month": 202101, "end_month": 202212}],
    )
    expect_rows(
        session,
        checks,
        "直接查询使用人物边",
        "MATCH (a:person)-[:same_company]-(b:person) "
        'WHERE id(a)=="p:expert:101" '
        "RETURN DISTINCT id(b) AS person_id ORDER BY person_id LIMIT 100",
        [{"person_id": p} for p in ["p:expert:104", "p:resume:102", "p:resume:103"]],
    )
    expect_rows(
        session,
        checks,
        "两条人物边连接一位中间人物",
        "MATCH (a:person)-[:same_company]-(m:person)-[:same_company]-(b:person) "
        'WHERE id(a)=="p:expert:101" AND id(b)=="p:expert:105" '
        "AND id(m)!=id(a) AND id(m)!=id(b) "
        "RETURN DISTINCT id(m) AS middle_id ORDER BY middle_id LIMIT 100",
        [{"middle_id": "p:resume:102"}],
    )
    expect_rows(
        session,
        checks,
        "没有教育时间仍预计算同校",
        "MATCH (a:person)-[r:same_school]-(b:person) "
        'WHERE id(a)=="p:expert:101" '
        "RETURN id(b) AS person_id,r.left_fact_rank AS left_rank, "
        "r.right_fact_rank AS right_rank LIMIT 100",
        [{"person_id": "p:expert:105", "left_rank": 8001, "right_rank": 8002}],
    )


def check_same_major(session: Any, checks: list[dict[str, Any]]) -> None:
    expect_rows(
        session,
        checks,
        "同专业不要求共同学校或教育时间且反向证据归属不变",
        "MATCH (a:person)-[r:same_major]-(b:person) "
        'WHERE id(a)=="p:resume:102" '
        "RETURN id(b) AS person_id,r.entity_vid AS major_vid,"
        "r.left_fact_rank AS left_rank,r.right_fact_rank AS right_rank LIMIT 100",
        [{"person_id": "p:expert:101", "major_vid": MAJOR, "left_rank": 9001, "right_rank": 9002}],
    )


def check_complete_rows(
    session: Any, rows: list[dict[str, Any]], checks: list[dict[str, Any]], *, corrected: bool
) -> None:
    fixture = json.loads(EXPECTED.read_text())
    actual = [[row.get(field) for field in fixture["columns"]] for row in rows]
    expected = fixture["after" if corrected else "before"]
    if sorted(actual) != sorted(expected):
        raise AssertionError("图计算与完整人工预期不一致")
    sources = ",".join(
        json.dumps(p)
        for p in [
            "p:expert:101",
            "p:expert:104",
            "p:expert:105",
            "p:resume:102",
            "p:resume:103",
            "p:resume:106",
        ]
    )
    returned = []
    for kind in RELATION_SOURCES:
        columns = (
            f'"{kind}" AS kind,src(edge) AS source,dst(edge) AS target,rank(edge) AS rank,'
            f"{kind}.entity_vid AS entity_vid,{kind}.left_fact_rank AS left_fact_rank,"
            f"{kind}.right_fact_rank AS right_fact_rank"
        )
        if kind == "company_overlap":
            columns += (
                f",{kind}.overlap_start_month AS overlap_start_month,"
                f"{kind}.overlap_end_month AS overlap_end_month"
            )
        returned.extend(
            query(session, f"GO FROM {sources} OVER {kind} YIELD {columns} | LIMIT 201")
        )
    if sorted(json.dumps(row, sort_keys=True) for row in returned) != sorted(
        json.dumps(row, sort_keys=True) for row in rows
    ):
        raise AssertionError("人物边完整回读与写入不一致")
    checks.append(
        {"name": "完整人工预期和全量人物边回读", "passed": True, "evidence_edges": len(rows)}
    )


def projection(session: Any, report: dict[str, Any], *, corrected: bool) -> None:
    space = require_space("relationship_lab_ddl_" + secrets.token_hex(6))
    run: dict[str, Any] = {"space": space, "corrected": corrected, "dropped": False, "checks": []}
    report["projections"].append(run)
    created = False
    try:
        query(
            session,
            f"CREATE SPACE `{space}` (partition_num=1,replica_factor=1,vid_type=FIXED_STRING(128))",
        )
        created = True
        query(session, f"USE `{space}`", wait=True)
        for statement in schema_statements() + extension_statements():
            query(session, statement, wait=True)
        create_fixture(session)
        verify_person_privacy(session, run["checks"])
        verify_business_information(session, run["checks"])
        if corrected:
            # 明确模拟上游失效的结果，在第二个新空间构建期间移除，旧空间不更新。
            query(session, f'DELETE EDGE worked_at "p:expert:101"->"{COMPANY_A}"@7001')
        try:
            calculate(session, budget=1)
        except RelationBudgetExceeded:
            run["budget_failure_before_relation_writes"] = True
        else:
            raise AssertionError("预算耗尽未阻断")
        rows = calculate(session, budget=200)
        expected = {
            "same_company": 9 if corrected else 12,
            "company_overlap": 0 if corrected else 1,
            "same_school": 1,
            "same_major": 1,
        }
        counts = {kind: sum(r["kind"] == kind for r in rows) for kind in expected}
        if counts != expected:
            raise AssertionError("独立预期的关系证据数不符")
        run["counts"] = counts
        run["derived_rows"] = rows
        insert_relations(session, rows)
        check_complete_rows(session, rows, run["checks"], corrected=corrected)
        check_relations(session, run["checks"], corrected=corrected)
        check_same_major(session, run["checks"])
        run["edge_descriptions"] = {
            kind: query(session, f"DESCRIBE EDGE {kind}") for kind in expected
        }
    finally:
        if created:
            query(session, f"DROP SPACE `{space}`")
            run["dropped"] = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "model": MODEL,
        "date": "2026-11-06",
        "status": "failed",
        "reference_month": 202611,
        "projections": [],
        "base_sha256": hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
        "extension_sha256": hashlib.sha256(EXTENSION.read_bytes()).hexdigest(),
        "expected_sha256": hashlib.sha256(EXPECTED.read_bytes()).hexdigest(),
        "scope": "fictional graph-only import demo, no SQL/API integration or production capacity",
    }
    with args.output.open("x") as output:
        try:
            with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
                projection(session, report, corrected=False)
                projection(session, report, corrected=True)
            report["status"] = "passed"
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            raise
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print("人物关系预计算演练通过：原快照15条、修正快照11条人物证据边，两个临时空间已清理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
