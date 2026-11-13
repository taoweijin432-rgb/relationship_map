"""在新建临时空间验证 uuid-facts-v3 的业务属性，不写人物姓名或切换服务。"""

import argparse
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
    require_space,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "infra/nebula/schema/uuid-facts-v3.ngql"
COMPANY_A = "e:11111111-1111-4111-8111-111111111111"
COMPANY_B = "e:22222222-2222-4222-8222-222222222222"
SCHOOL = "e:33333333-3333-4333-8333-333333333333"
MAJOR = "e:44444444-4444-4444-8444-444444444444"


def schema_statements() -> list[str]:
    text = "\n".join(
        line for line in SCHEMA.read_text().splitlines() if not line.lstrip().startswith("--")
    )
    statements = [part.strip() for part in text.split(";") if part.strip()]
    if not all(part.startswith(("CREATE TAG ", "CREATE EDGE ")) for part in statements):
        raise ValueError("验证只接受固定文件中的 TAG／EDGE 创建语句")
    return statements


def create_fixture(session: Any) -> None:
    people = [
        f'"p:expert:101":("expert","E{101:018d}")',
        f'"p:resume:102":("resume","R{102:018d}")',
        f'"p:resume:103":("resume","R{103:018d}")',
        f'"p:expert:104":("expert","E{104:018d}")',
        f'"p:expert:105":("expert","E{105:018d}")',
        f'"p:resume:106":("resume","R{106:018d}")',
    ]
    query(
        session,
        "INSERT VERTEX person(source_system,serial_number) VALUES " + ",".join(people),
        wait=True,
    )
    query(
        session,
        f"INSERT VERTEX company(name,company_code) VALUES "
        f'"{COMPANY_A}":("虚构公司甲","MOCK-C01"),'
        f'"{COMPANY_B}":("虚构公司乙","MOCK-C02")',
        wait=True,
    )
    query(
        session,
        f'INSERT VERTEX school(name,school_code) VALUES "{SCHOOL}":("虚构学校","MOCK-S01")',
        wait=True,
    )
    query(
        session,
        f'INSERT VERTEX major(name,major_code) VALUES "{MAJOR}":("虚构专业","MOCK-M01")',
        wait=True,
    )
    work = [
        ("p:expert:101", COMPANY_A, 7001, "202001,202212,false"),
        ("p:expert:101", COMPANY_A, 7002, "200801,200912,false"),
        ("p:resume:102", COMPANY_A, 7003, "202101,NULL,true"),
        ("p:resume:103", COMPANY_A, 7004, "201001,201212,false"),
        ("p:expert:104", COMPANY_A, 7005, "NULL,NULL,false"),
        ("p:expert:105", COMPANY_B, 7006, "202201,202212,false"),
        ("p:resume:102", COMPANY_B, 7007, "202401,NULL,true"),
        ("p:resume:106", COMPANY_B, 7008, "202301,202312,false"),
    ]
    titles = ["工程师", "分析师", "研究员", "经理", "顾问", "总监", "工程师", "研究员"]
    values = ",".join(
        f'"{p}"->"{c}"@{rank}:({props},'
        f"{json.dumps(mock_experience_key(p, 'work', rank - 7000))},{json.dumps(title)})"
        for (p, c, rank, props), title in zip(work, titles, strict=True)
    )
    query(
        session,
        "INSERT EDGE worked_at(start_month,end_month,is_current,experience_key,position_title) "
        "VALUES " + values,
        wait=True,
    )
    query(
        session,
        "INSERT EDGE studied_at(start_month,end_month,experience_key,education_level,"
        "is_regular_enrollment) VALUES "
        f'"p:expert:101"->"{SCHOOL}"@8001:'
        '(NULL,NULL,"expert:experts_education_experience:11","硕士","是"),'
        f'"p:expert:105"->"{SCHOOL}"@8002:'
        '(NULL,NULL,"expert:experts_education_experience:12","本科",NULL)',
        wait=True,
    )
    query(
        session,
        "INSERT EDGE studied_major(start_month,end_month,experience_key,education_level,"
        "is_regular_enrollment) VALUES "
        f'"p:expert:101"->"{MAJOR}"@9001:'
        '(NULL,NULL,"expert:experts_education_experience:11","硕士","是"),'
        f'"p:resume:102"->"{MAJOR}"@9002:'
        '(NULL,NULL,"resume:resume_education_experience:21","硕士",NULL)',
        wait=True,
    )


def mock_experience_key(person: str, kind: str, row_id: int) -> str:
    source = person.split(":")[1]
    prefix = "experts" if source == "expert" else "resume"
    table = f"{prefix}_{'work' if kind == 'work' else 'education'}_experience"
    return f"{source}:{table}:{row_id}"


def expect_rows(
    session: Any,
    checks: list[dict[str, Any]],
    name: str,
    statement: str,
    expected: list[dict[str, Any]],
) -> None:
    actual = query(session, statement)
    passed = actual == expected
    checks.append(
        {"name": name, "passed": passed, "sql": statement, "expected": expected, "actual": actual}
    )
    if not passed:
        raise AssertionError(f"图 DDL 验证结果不符：{name}")


def verify_business_queries(session: Any, checks: list[dict[str, Any]]) -> None:
    pair = (
        "MATCH (a:person)-[ea:worked_at]->(c:company)<-[eb:worked_at]-(b:person) "
        'WHERE id(a)=="p:expert:101" AND id(b)!=id(a) '
    )
    expect_rows(
        session,
        checks,
        "共同公司保留非同期和未知日期",
        pair + "RETURN DISTINCT id(b) AS person_id ORDER BY person_id LIMIT 100",
        [{"person_id": p} for p in ["p:expert:104", "p:resume:102", "p:resume:103"]],
    )
    expect_rows(
        session,
        checks,
        "候选来源限制",
        pair + 'AND b.person.source_system=="resume" '
        "RETURN DISTINCT id(b) AS person_id ORDER BY person_id LIMIT 100",
        [{"person_id": "p:resume:102"}, {"person_id": "p:resume:103"}],
    )
    overlap = (
        "AND ea.start_month IS NOT NULL AND eb.start_month IS NOT NULL "
        "AND (ea.is_current OR ea.end_month IS NOT NULL) "
        "AND (eb.is_current OR eb.end_month IS NOT NULL) "
        "AND ea.start_month <= (CASE WHEN eb.is_current THEN 202611 ELSE eb.end_month END) "
        "AND eb.start_month <= (CASE WHEN ea.is_current THEN 202611 ELSE ea.end_month END) "
    )
    expect_rows(
        session,
        checks,
        "同期由图计算且证据Rank明确",
        pair + overlap + "RETURN id(b) AS person_id, rank(ea) AS left_rank, rank(eb) AS right_rank "
        "ORDER BY person_id LIMIT 100",
        [{"person_id": "p:resume:102", "left_rank": 7001, "right_rank": 7003}],
    )
    expect_rows(
        session,
        checks,
        "重复任职不被覆盖",
        'GO FROM "p:expert:101" OVER worked_at YIELD rank(edge) AS edge_rank '
        "| ORDER BY $-.edge_rank | LIMIT 100",
        [{"edge_rank": 7001}, {"edge_rank": 7002}],
    )
    expect_rows(
        session,
        checks,
        "无教育时间仍有同校",
        "MATCH (a:person)-[:studied_at]->(s:school)<-[:studied_at]-(b:person) "
        'WHERE id(a)=="p:expert:101" AND id(b)!=id(a) '
        "RETURN DISTINCT id(b) AS person_id ORDER BY person_id LIMIT 100",
        [{"person_id": "p:expert:105"}],
    )
    expect_rows(
        session,
        checks,
        "一位中间人物的公司连接链",
        "MATCH (a:person)-[:worked_at]->(c1:company)<-[:worked_at]-(m:person)"
        "-[:worked_at]->(c2:company)<-[:worked_at]-(b:person) "
        'WHERE id(a)=="p:expert:101" AND id(b)=="p:expert:105" '
        "AND id(m)!=id(a) AND id(m)!=id(b) AND id(c1)!=id(c2) "
        "RETURN DISTINCT id(m) AS middle_id ORDER BY middle_id LIMIT 100",
        [{"middle_id": "p:resume:102"}],
    )


def verify_constraints(session: Any, checks: list[dict[str, Any]]) -> None:
    for name, statement in [
        (
            "人物来源NOT NULL",
            "INSERT VERTEX person(source_system,serial_number) "
            'VALUES "p:expert:999":(NULL,"MOCK-999")',
        ),
        (
            "工作状态NOT NULL",
            "INSERT EDGE worked_at(start_month,end_month,is_current,experience_key) "
            f'VALUES "p:expert:101"->"{COMPANY_A}"@99997:'
            '(NULL,NULL,NULL,"expert:experts_work_experience:99997")',
        ),
    ]:
        result = session.execute(statement)
        passed = not result.is_succeeded()
        checks.append(
            {"name": name, "passed": passed, "sql": statement, "error_code": result.error_code()}
        )
        if not passed:
            raise AssertionError(f"NOT NULL 未生效：{name}")
    # 故意向本次临时空间写错端点和月份，实证它们不是 DDL 自动约束。
    statement = "INSERT EDGE worked_at(start_month,end_month,is_current,experience_key) "
    statement += f'VALUES "p:expert:101"->"{SCHOOL}"@99998:'
    statement += '(202013,202001,false,"expert:experts_work_experience:99998")'
    query(session, statement)
    checks.append(
        {
            "name": "端点类别和月份语义需应用预检",
            "passed": True,
            "database_accepts_invalid_business_values": True,
            "sql": statement,
        }
    )
    query(session, f'DELETE EDGE worked_at "p:expert:101"->"{SCHOOL}"@99998')


def verify_control(session: Any, checks: list[dict[str, Any]]) -> None:
    # 摘要仅标记虚构测试，不声称是已完成真实 SQL 冻结的摘要。
    digest = hashlib.sha256(b"fictional-ddl-fixture-v1").hexdigest()
    query(
        session,
        "INSERT VERTEX projection_meta(schema_version,projection_id,"
        "snapshot_sha256,reference_month,state) VALUES "
        f'"meta:projection":("uuid-facts-v3","fictional-ddl-test","{digest}",'
        '202611,"staging")',
        wait=True,
    )
    expect_rows(
        session,
        checks,
        "控制节点字段可回读",
        'FETCH PROP ON projection_meta "meta:projection" '
        "YIELD properties(vertex).schema_version AS version, "
        "properties(vertex).reference_month AS month, properties(vertex).state AS state",
        [{"version": "uuid-facts-v3", "month": 202611, "state": "staging"}],
    )


def verify_person_privacy(session: Any, checks: list[dict[str, Any]]) -> None:
    description = query(session, "DESCRIBE TAG person")
    allowed = {"source_system", "serial_number"}
    if {row["Field"] for row in description} != allowed:
        raise AssertionError("人物标签不符合来源与业务编号白名单")
    vids = [
        "p:expert:101",
        "p:resume:102",
        "p:resume:103",
        "p:expert:104",
        "p:expert:105",
        "p:resume:106",
    ]
    statement = "FETCH PROP ON person " + ",".join(json.dumps(vid) for vid in vids)
    rows = query(session, statement + " YIELD id(vertex) AS vid, properties(vertex) AS attrs")
    if len(rows) != len(vids) or any(set(row["attrs"]) != allowed for row in rows):
        raise AssertionError("人物节点回读存在额外属性或节点缺失")
    checks.append(
        {
            "name": "人物属性白名单及六节点完整回读",
            "passed": True,
            "description": description,
            "actual": rows,
        }
    )
    # 使用固定虚构探针验证旧写法被拒绝，不传入任何真实姓名。
    result = session.execute(
        "INSERT VERTEX person(name,source_system,serial_number) "
        'VALUES "p:expert:999":("privacy-test-canary","expert","MOCK-999")'
    )
    if result.is_succeeded():
        raise AssertionError("姓名属性写入未被拒绝")
    checks.append(
        {"name": "旧姓名字段写入被拒绝", "passed": True, "error_code": result.error_code()}
    )


def verify_business_information(session: Any, checks: list[dict[str, Any]]) -> None:
    expect_rows(
        session,
        checks,
        "业务编号与人物来源一起回读",
        'FETCH PROP ON person "p:expert:101" YIELD '
        "properties(vertex).source_system AS source,properties(vertex).serial_number AS number",
        [{"source": "expert", "number": f"E{101:018d}"}],
    )
    expect_rows(
        session,
        checks,
        "重复任职职位与经历组键保持分离",
        'GO FROM "p:expert:101" OVER worked_at YIELD '
        "rank(edge) AS fact_rank,worked_at.position_title AS title,"
        "worked_at.experience_key AS experience_key | ORDER BY $-.fact_rank | LIMIT 100",
        [
            {
                "fact_rank": 7001,
                "title": "工程师",
                "experience_key": "expert:experts_work_experience:1",
            },
            {
                "fact_rank": 7002,
                "title": "分析师",
                "experience_key": "expert:experts_work_experience:2",
            },
        ],
    )
    expect_rows(
        session,
        checks,
        "学校与专业按同条教育经历配对",
        "MATCH (p:person)-[s:studied_at]->(school:school),"
        "(p)-[m:studied_major]->(major:major) "
        'WHERE id(p)=="p:expert:101" AND s.experience_key==m.experience_key '
        "RETURN s.experience_key AS experience_key,s.education_level AS level,"
        "s.is_regular_enrollment AS enrollment,"
        "m.education_level==s.education_level AS consistent LIMIT 100",
        [
            {
                "experience_key": "expert:experts_education_experience:11",
                "level": "硕士",
                "enrollment": "是",
                "consistent": True,
            }
        ],
    )


def verify(report: dict[str, Any]) -> None:
    statements = schema_statements()
    space = require_space("relationship_lab_ddl_" + secrets.token_hex(6))
    report["space"] = space
    with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
        created = False
        try:
            query(
                session,
                f"CREATE SPACE `{space}` "
                "(partition_num=1,replica_factor=1,vid_type=FIXED_STRING(128))",
            )
            created = True
            query(session, f"USE `{space}`", wait=True)
            for statement in statements:
                query(session, statement, wait=True)
            report["tags"] = query(session, "SHOW TAGS")
            report["edges"] = query(session, "SHOW EDGES")
            report["descriptions"] = {
                name: query(session, f"DESCRIBE {kind} `{name}`")
                for kind, names in [
                    ("TAG", ["person", "company", "school", "major", "projection_meta"]),
                    ("EDGE", ["worked_at", "studied_at", "studied_major"]),
                ]
                for name in names
            }
            create_fixture(session)
            verify_person_privacy(session, report["checks"])
            verify_business_information(session, report["checks"])
            verify_business_queries(session, report["checks"])
            verify_constraints(session, report["checks"])
            verify_control(session, report["checks"])
        finally:
            if created:
                query(session, f"DROP SPACE `{space}`")
                report["temporary_space_dropped"] = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": "uuid-facts-v3",
        "date": "2026-11-06",
        "status": "failed",
        "schema_sha256": hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
        "scope": "local fictional DDL smoke; no MySQL, Supabase, API migration or capacity test",
        "checks": [],
        "temporary_space_dropped": False,
    }
    # 先独占报告文件，避免跑完后才发现同名记录已存在。
    with args.output.open("x") as output:
        try:
            verify(report)
            report["status"] = "passed"
        except Exception as exc:
            # 明确保留失败状态；不输出 SDK 可能包含凭据的异常文本。
            report["error_type"] = type(exc).__name__
            print(f"DDL 验证失败：{type(exc).__name__}；详情见新报告")
            raise
        finally:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(f"DDL 验证通过：{len(report['checks'])} 项；本次空间已清理")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
