"""可复现的虚构履历、手工关系用例及独立关系参照，供MySQL更新实验使用。"""

import copy
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
MONTH = 202611
KINDS = ("same_company", "company_overlap", "same_school", "same_major")
STAMP = "2026-11-01 09:00:00.123456"


class FictionalCareers:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.profiles: dict[str, dict[str, Any]] = {}
        self.entities: dict[tuple[str, int], str] = {}
        self.rank = 10000
        self.rows["graph_sync_batch"] = [
            {
                "id": 1,
                "source_project_id": "fictional-career-lab",
                "sync_mode": "full",
                "status": "succeeded",
                "started_at": STAMP,
                "snapshot_at": STAMP,
                "finished_at": STAMP,
                "expected_counts": None,
                "actual_counts": None,
                "error_message": None,
            }
        ]

    def entity(self, kind: str, identity: int, name: str) -> int:
        if (kind, identity) in self.entities:
            return identity
        self.entities[kind, identity] = name
        row = {
            "id": identity,
            "uuid": str(uuid5(NAMESPACE_URL, f"fictional/{kind}/{identity}")),
            f"{kind}_code": f"{kind.upper()}-{identity}",
            "standard_name": name,
            "verification_status": "模拟有效",
            "source_created_at": STAMP,
            "source_updated_at": STAMP,
            "sync_batch_id": 1,
            "synced_at": STAMP,
            "deleted_at": None,
        }
        if kind in {"company", "school"}:
            row["former_names"] = json.dumps([], ensure_ascii=False)
        if kind == "company":
            row.update(child_company_codes="0", parent_company_codes="0")
        if kind == "school":
            row.update(
                official_code=f"00{identity:05}", country_region="中国", city="澄州市"
            )
        self.rows[f"graph_{kind}_entity"].append(row)
        return identity

    def person(self, source: str, identity: int, name: str, note: str) -> str:
        table = "experts" if source == "expert" else "resume"
        pid = f"p:{source}:{identity}"
        row = {
            "id": identity,
            "serial_number": f"{'EXP' if source == 'expert' else 'RES'}202611{identity:010}",
            "name": name,
            "interview_nickname": name,
            "company": "",
            "job_name": "",
            "background": f"纯虚构测试履历。{note}",
            "source_type": 1,
            "created_at": STAMP[:19],
            "updated_at": STAMP[:19],
            "age": 42,
        }
        self.rows[table].append(row)
        self.profiles[pid] = {
            "person": pid,
            "name": name,
            "note": note,
            "work": [],
            "education": [],
        }
        return pid

    def _mapping(
        self, pid: str, table: str, row: int, field: str, kind: str, target: int
    ) -> int:
        self.rank += 1
        self.rows["graph_edge_mapping"].append(
            {
                "id": self.rank,
                "source_system": pid.split(":")[1],
                "source_table": table,
                "source_field_id": row,
                "source_field": field,
                "source_person_id": int(pid.split(":")[2]),
                "standard_entity_id": target,
                "edge_type": kind,
                "created_at": STAMP,
                "updated_at": STAMP,
                "deleted_at": None,
            }
        )
        return self.rank

    def work(
        self,
        pid: str,
        company: int,
        start: str | None,
        end: str | None,
        title: str,
        *,
        current: bool = False,
    ) -> None:
        source, identity = pid.split(":")[1:]
        prefix, column = (
            ("experts", "expert_id") if source == "expert" else ("resume", "resume_id")
        )
        table = prefix + "_work_experience"
        row_id = len(self.rows[table]) + 1
        self.rows[table].append(
            {
                "id": row_id,
                column: int(identity),
                "company_name": self.entities["company", company],
                "start_date": start,
                "end_date": end,
                "position_title": title,
                "work_description": "虚构履历，用于关系与更新验证",
                "is_employed": 1 if current else 2,
                "created_at": STAMP[:19],
                "updated_at": STAMP[:19],
            }
        )
        rank = self._mapping(pid, table, row_id, "company_name", "worked_at", company)
        self.profiles[pid]["work"].append(
            {
                "company": company,
                "company_name": self.entities["company", company],
                "start": start,
                "end": end,
                "title": title,
                "current": current,
                "rank": rank,
            }
        )
        if current:
            person = next(
                row for row in self.rows[prefix] if row["id"] == int(identity)
            )
            person.update(company=self.entities["company", company], job_name=title)

    def education(
        self,
        pid: str,
        school: int,
        major: int,
        year: int = 2004,
        *,
        masters: bool = False,
    ) -> None:
        source, identity = pid.split(":")[1:]
        prefix, column = (
            ("experts", "expert_id") if source == "expert" else ("resume", "resume_id")
        )
        table = prefix + "_education_experience"
        row_id = len(self.rows[table]) + 1
        self.rows[table].append(
            {
                "id": row_id,
                column: int(identity),
                "school_name": self.entities["school", school],
                "major": self.entities["major", major],
                "education_level": "硕士" if masters else "本科",
                "is_regular_enrollment": "非统招" if masters else "统招",
                "start_date": f"{year}-09-01",
                "end_date": f"{year + (3 if masters else 4)}-06-30",
                "create_by": 1,
                "created_at": STAMP[:19],
                "updated_at": STAMP[:19],
            }
        )
        school_rank = self._mapping(
            pid, table, row_id, "school_name", "studied_at", school
        )
        major_rank = self._mapping(pid, table, row_id, "major", "studied_major", major)
        self.profiles[pid]["education"].append(
            {
                "school": school,
                "school_name": self.entities["school", school],
                "major": major,
                "major_name": self.entities["major", major],
                "year": year,
                "masters": masters,
                "school_rank": school_rank,
                "major_rank": major_rank,
            }
        )


def manual_cases(data: FictionalCareers) -> list[dict[str, Any]]:
    names = [
        "陈亦舟",
        "林知夏",
        "周景行",
        "许清越",
        "沈书宁",
        "陆予安",
        "程望舒",
        "叶星澜",
        "顾明川",
        "唐以南",
        "苏沐言",
        "江云岑",
        "宋怀瑾",
        "徐听岚",
        "梁知远",
        "方初禾",
        "谢庭轩",
        "温若溪",
        "秦予墨",
        "韩时雨",
        "杜言蹊",
        "蒋清和",
    ]
    people = [
        data.person(
            "expert" if index % 2 == 0 else "resume",
            index // 2 + 1,
            name,
            "手工设计的关系场景，机构及人物均为虚构",
        )
        for index, name in enumerate(names)
    ]
    regions = [
        "澄川",
        "云岫",
        "远岚",
        "星浦",
        "青禾",
        "临溪",
        "松原",
        "映湖",
        "景江",
        "岚溪",
        "宁川",
        "溪海",
        "清浦",
        "南岑",
        "云洲",
        "青沅",
        "东岚",
        "西澄",
        "新溪",
        "安浦",
        "沐川",
        "明岑",
    ]
    private_majors = [
        "电子科学与技术",
        "电子信息工程",
        "智能科学与技术",
        "财政学",
        "金融数学",
        "管理科学",
        "数学与应用数学",
        "图书馆学",
        "应用物理学",
        "公共事业管理",
        "保险学",
        "采购管理",
        "机械电子工程",
        "过程装备与控制工程",
        "国际经济与贸易",
        "社会学",
        "应用化学",
        "人力资源管理",
        "国际商务",
        "土地资源管理",
        "药学",
        "药物制剂",
    ]
    for index, pid in enumerate(people):
        data.entity(
            "company", 1000 + index, f"{regions[index]}知行产业研究有限公司（虚构）"
        )
        data.entity("school", 1000 + index, f"{regions[index]}综合大学（虚构）")
        data.entity("major", 1000 + index, private_majors[index])
        data.work(pid, 1000 + index, "2025-01-01", None, "行业研究负责人", current=True)
    shared_names = {
        "company": [
            "澜桥软件科技",
            "远岚信息技术",
            "青禾企业管理",
            "云港供应链",
            "星浦精密制造",
            "景川医疗科技",
        ],
        "school": [
            "北岚工程学院",
            "临川财经大学",
            "云溪技术大学",
            "星浦师范大学",
            "青禾工商学院",
            "景川金融学院",
            "沐海理工大学",
            "南岑经济学院",
        ],
        "major": [
            "集成电路设计与集成系统",
            "光电信息科学与工程",
            "信息资源管理",
            "交通工程",
            "车辆工程",
            "金融学",
            "信息与计算科学",
            "经济学",
        ],
    }
    for kind, labels in shared_names.items():
        for identity, label in enumerate(labels, 1):
            data.entity(kind, identity, label + ("（虚构）" if kind != "major" else ""))
    # 四个独立三人组，端点没有直接关系，中间人分别连接不同关系类型。
    data.work(people[0], 1, "2014-07-01", "2018-12-31", "研发工程师")
    data.work(people[1], 1, "2016-01-01", "2018-12-31", "测试工程师")
    data.work(people[1], 2, "2019-01-01", "2024-12-31", "质量经理")
    data.work(people[2], 2, "2020-01-01", "2023-12-31", "产品经理")
    data.work(people[3], 3, "2015-01-01", "2021-12-31", "财务分析师")
    data.work(people[4], 3, "2018-01-01", "2022-12-31", "预算经理")
    data.work(people[10], 4, "2018-01-01", "2023-12-31", "供应链经理")
    data.work(people[11], 4, "2020-01-01", "2024-12-31", "采购经理")
    data.work(people[12], 5, "2010-01-01", "2012-12-31", "机械工程师")
    data.work(people[13], 5, "2020-01-01", "2022-12-31", "工艺工程师")
    school_overrides = {4: 2, 5: 2, 6: 3, 7: 3, 14: 6, 15: 6, 16: 7, 17: 7, 18: 1002}
    major_overrides = {7: 3, 8: 3, 9: 4, 10: 4, 14: 6, 15: 6, 16: 7, 17: 8}
    for index, pid in enumerate(people):
        data.education(
            pid,
            school_overrides.get(index, 1000 + index),
            major_overrides.get(index, 1000 + index),
            1998 if index == 15 else 2004,
        )
    data.education(people[16], 8, 8, 2010, masters=True)
    data.work(people[20], 6, None, "2021-12-31", "临床项目协调员")
    data.work(people[21], 6, "2019-01-01", "2022-12-31", "医学项目经理")
    cases = []
    for label, left, middle, right in [
        ("公司→公司", 0, 1, 2),
        ("公司→学校", 3, 4, 5),
        ("学校→专业", 6, 7, 8),
        ("专业→公司", 9, 10, 11),
    ]:
        cases.append(
            {
                "name": label,
                "left": people[left],
                "right": people[right],
                "direct": [],
                "middle": [people[middle]],
            }
        )
    cases.extend(
        [
            {
                "name": "同公司非同期",
                "left": people[12],
                "right": people[13],
                "direct": ["same_company"],
                "middle": [],
            },
            {
                "name": "同校同专业但毕业年代不同",
                "left": people[14],
                "right": people[15],
                "direct": ["same_major", "same_school"],
                "middle": [],
            },
            {
                "name": "学校与专业来自不同教育行",
                "left": people[16],
                "right": people[17],
                "direct": ["same_major", "same_school"],
                "middle": [],
            },
            {
                "name": "三条边链超出一位中间人范围",
                "left": people[0],
                "right": people[18],
                "direct": [],
                "middle": [],
            },
            {
                "name": "独立人物无连接",
                "left": people[19],
                "right": people[0],
                "direct": [],
                "middle": [],
            },
            {
                "name": "日期未知仅同公司",
                "left": people[20],
                "right": people[21],
                "direct": ["same_company"],
                "middle": [],
            },
        ]
    )
    return cases


def make_dataset() -> tuple[
    dict[str, list[dict[str, Any]]], list[dict[str, Any]], dict[str, Any]
]:
    data = FictionalCareers()
    cases = manual_cases(data)
    industries = [
        ("信息技术", "软件工程", "后端工程师", "技术负责人"),
        ("医疗器械", "生物医学工程", "研发工程师", "注册项目经理"),
        ("新能源", "电气工程", "控制工程师", "系统研发经理"),
        ("精密制造", "机械工程", "工艺工程师", "制造工程经理"),
        ("物流供应链", "物流管理", "运营分析师", "供应链经理"),
        ("企业服务", "会计学", "财务分析师", "财务经理"),
    ]
    surnames = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张"
    given_names = [
        "清越",
        "亦宁",
        "知衡",
        "予川",
        "景辰",
        "书禾",
        "云舒",
        "思远",
        "沐青",
        "怀序",
    ]
    majors = [
        ["软件工程", "计算机科学与技术", "网络工程", "信息安全"],
        ["生物医学工程", "医学影像技术", "材料科学与工程", "医学检验技术"],
        ["电气工程及其自动化", "自动化", "能源与动力工程", "高分子材料与工程"],
        ["机械设计制造及其自动化", "工业工程", "材料成型及控制工程", "测控技术与仪器"],
        ["物流管理", "工程管理", "交通运输", "信息管理与信息系统"],
        ["会计学", "财务管理", "审计学", "经济统计学"],
    ]
    brands = [
        "澄川云帆",
        "青岚慧源",
        "云溪启衡",
        "松原知行",
        "远岚瑞景",
        "星浦明远",
        "临溪清源",
        "映湖致新",
        "景江信达",
        "岚溪恒川",
        "宁川望舒",
        "溪海景辰",
    ]
    school_regions = ["澄川", "青岚", "云溪", "松原", "远岚", "星浦", "临溪", "映湖"]
    school_kinds = [
        "信息科技大学",
        "医科大学",
        "能源工程学院",
        "工业大学",
        "交通大学",
        "财经大学",
    ]
    for group, (industry, _, junior, senior) in enumerate(industries):
        for item in range(12):
            data.entity(
                "company",
                100 + group * 12 + item,
                f"{brands[item]}{industry}有限公司（虚构）",
            )
        for item in range(8):
            data.entity(
                "school",
                100 + group * 8 + item,
                f"{school_regions[item]}{school_kinds[group]}（虚构）",
            )
        for item in range(4):
            data.entity(
                "major",
                100 + group * 4 + item,
                majors[group][item],
            )
        for offset in range(40):
            number = group * 40 + offset
            source = "expert" if number % 2 == 0 else "resume"
            pid = data.person(
                source,
                100 + number // 2,
                surnames[number % len(surnames)] + given_names[number // len(surnames)],
                f"{industry}从业者，先接受相关专业教育，再按时间顺序任职",
            )
            graduation = 2006 + number % 8
            school = 100 + group * 8 + offset % 8
            degree = 100 + group * 4 + (offset // 2) % 4
            data.education(pid, school, degree, graduation - 4)
            first = 100 + group * 12 + offset % 12
            current = 100 + group * 12 + (offset + 5) % 12
            if offset % 7:
                data.work(
                    pid, first, f"{graduation}-07-01", f"{graduation + 4}-12-31", junior
                )
            data.work(
                pid, current, f"{graduation + 5}-01-01", None, senior, current=True
            )
            if offset % 10 == 0:
                data.education(
                    pid,
                    100 + group * 8 + (offset + 3) % 8,
                    degree,
                    graduation + 5,
                    masters=True,
                )
    # 同名不同实体、跨类型整数碰撞、大BIGINT和多证据分别保存。
    data.entity("company", 9007199254740993, data.entities["company", 1019])
    data.work("p:expert:10", 9007199254740993, "2016-01-01", "2019-12-31", "行业分析师")
    data.work("p:expert:7", 5, "2016-01-01", "2018-12-31", "高级机械工程师")
    cases.append(
        {
            "name": "同名公司不同实体",
            "left": "p:expert:10",
            "right": "p:resume:10",
            "direct": [],
            "middle": [],
        }
    )
    data.rank = 9007199254740993
    data.work("p:expert:11", 1000, "2010-01-01", "2012-12-31", "研究助理")
    for table in ("experts_project_experience", "resume_project_experience"):
        data.rows[table] = []
    for pid, profile in data.profiles.items():
        source, identity = pid.split(":")[1:]
        table = "experts" if source == "expert" else "resume"
        person = next(row for row in data.rows[table] if row["id"] == int(identity))
        person["age"] = 2026 - (min(row["year"] for row in profile["education"]) - 18)
        person["education"] = (
            "硕士" if any(row["masters"] for row in profile["education"]) else "本科"
        )
    return dict(data.rows), cases, data.profiles


def expected_relations(
    rows: dict[str, list[dict[str, Any]]], month: int = MONTH
) -> list[dict]:
    """独立原表参照，按实体分组及组合逐对比较，不调用投影、查询或生产日期函数。"""
    index = {name: {row["id"]: row for row in values} for name, values in rows.items()}
    groups: dict[tuple[str, int], list[tuple[dict, dict]]] = defaultdict(list)
    for edge in rows["graph_edge_mapping"]:
        raw = index[edge["source_table"]][edge["source_field_id"]]
        prefix = "experts" if edge["source_system"] == "expert" else "resume"
        person = index[prefix][edge["source_person_id"]]
        entity_kind = {
            "worked_at": "company",
            "studied_at": "school",
            "studied_major": "major",
        }[edge["edge_type"]]
        entity = index[f"graph_{entity_kind}_entity"][edge["standard_entity_id"]]
        if (
            any(row.get("deleted_at") for row in (edge, raw, person, entity))
            or entity["verification_status"] != "模拟有效"
        ):
            continue
        groups[edge["edge_type"], edge["standard_entity_id"]].append((edge, raw))
    result = []
    for (kind, entity), records in groups.items():
        for (left, raw_left), (right, raw_right) in combinations(records, 2):
            left_id = f"p:{left['source_system']}:{left['source_person_id']}"
            right_id = f"p:{right['source_system']}:{right['source_person_id']}"
            if left_id == right_id:
                continue
            if left_id > right_id:
                left, right, raw_left, raw_right = right, left, raw_right, raw_left
                left_id, right_id = right_id, left_id
            category = {
                "worked_at": "company",
                "studied_at": "school",
                "studied_major": "major",
            }[kind]
            proof = {
                "source": left_id,
                "target": right_id,
                "properties": {
                    "entity_vid": f"e:{category}:{entity}",
                    "left_fact_rank": left["id"],
                    "right_fact_rank": right["id"],
                },
            }
            result.append(
                {
                    **proof,
                    "type": {
                        "worked_at": "same_company",
                        "studied_at": "same_school",
                        "studied_major": "same_major",
                    }[kind],
                }
            )
            if kind != "worked_at":
                continue

            def month_number(value: str | None) -> int | None:
                return (
                    int(str(value)[:4]) * 12 + int(str(value)[5:7]) - 1
                    if value
                    else None
                )

            starts = [month_number(row["start_date"]) for row in (raw_left, raw_right)]
            ends = [
                month // 100 * 12 + month % 100 - 1
                if row["is_employed"] == 1
                else month_number(row["end_date"])
                for row in (raw_left, raw_right)
            ]
            if None in starts or None in ends:
                continue
            start, end = max(starts), min(ends)
            if start <= end:
                result.append(
                    {
                        "source": left_id,
                        "target": right_id,
                        "type": "company_overlap",
                        "properties": {
                            **proof["properties"],
                            "overlap_start_month": start // 12 * 100 + start % 12 + 1,
                            "overlap_end_month": end // 12 * 100 + end % 12 + 1,
                        },
                    }
                )
    return result


def distribution(rows: dict[str, list[dict]], relations: list[dict]) -> dict:
    company_people: dict[int, set[str]] = defaultdict(set)
    for edge in rows["graph_edge_mapping"]:
        if edge["edge_type"] == "worked_at":
            company_people[edge["standard_entity_id"]].add(
                f"{edge['source_system']}:{edge['source_person_id']}"
            )
    counts = Counter(row["type"] for row in relations)
    return {
        "people": len(rows["experts"]) + len(rows["resume"]),
        "companies": len(rows["graph_company_entity"]),
        "schools": len(rows["graph_school_entity"]),
        "majors": len(rows["graph_major_entity"]),
        "facts": len(rows["graph_edge_mapping"]),
        "max_people_per_company": max(map(len, company_people.values())),
        "relation_evidence": dict(counts),
    }


def contract_for(database: str) -> dict:
    contract = json.loads(
        (ROOT / "resources/examples/update-authoritative-contract-v1.json").read_text()
    )
    for binding in contract["tables"].values():
        binding["physical"] = database + "." + binding["physical"].split(".")[1]
    return copy.deepcopy(contract)
