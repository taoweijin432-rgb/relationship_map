"""显式创建的虚构数据，不对应任何生产来源表。"""

import random

from relationship_query.domain.models import Dataset, Entity, Fact, Person, Source

DATA_VERSION = "mock-v1"
REFERENCE_MONTH = 202611


def make_dataset(size: int = 60, seed: int = 42) -> Dataset:
    if size < 12:
        raise ValueError("数据集至少需要 12 人以保留边界场景")
    rng = random.Random(seed)
    organizations = ["星澜科技", "远川智能", "青禾生物", "云岫数据", "北辰制造", "观澜咨询"]
    schools = ["江城大学", "南洲理工大学", "海岳大学", "临川科技大学", "青岚大学"]
    roles = ["技术总监", "算法工程师", "产品经理", "研究员", "解决方案专家"]
    entities = _entities(organizations, schools, roles)
    people, facts = [], []
    given_names = ["知远", "予安", "明澈", "思宁", "景行", "清和", "亦舟", "若溪", "星野", "书言"]
    for i in range(1, size + 1):
        sources: list[Source] = ["expert"] if i % 4 == 1 else ["resume"]
        if i % 13 == 0:
            sources = ["expert", "resume"]
        name = (
            "林知远"
            if i in (1, 12)
            else "陈周沈许陆苏顾程方叶"[(i - 1) % 10] + given_names[(i // 10 + i) % 10]
        )
        org, role, school = (i - 1) % 6, (i - 1) % 5, (i - 1) % 5
        person_id = f"p:{i:06d}"
        people.append(
            Person(
                id=person_id,
                name=name,
                city=["上海", "北京", "杭州", "深圳"][i % 4],
                headline=f"{organizations[org]} · {roles[role]}",
                sources=sources,
                active=i != 11,
            )
        )
        source = sources[0]
        facts.extend(
            [
                Fact(
                    id=f"f:{i:06d}:work",
                    person_id=person_id,
                    type="employment",
                    entity_id=f"org:{org}",
                    role_id=f"role:{role}",
                    start_month=(2017 + rng.randrange(5)) * 100 + 1,
                    is_current=True,
                    source_system=source,
                    source_record_id=f"demo-work-{i}",
                ),
                Fact(
                    id=f"f:{i:06d}:school",
                    person_id=person_id,
                    type="education",
                    entity_id=f"school:{school}",
                    source_system=source,
                    source_record_id=f"demo-school-{i}",
                ),
            ]
        )
    facts = _edge_cases(facts)
    entity_names = {e.id: e.name for e in entities}
    people = [_refresh_headline(p, facts, entity_names) for p in people]
    return Dataset(
        version=DATA_VERSION if size == 60 else f"{DATA_VERSION}-{size}",
        reference_month=REFERENCE_MONTH,
        people=people,
        entities=entities,
        facts=facts,
    )


def _refresh_headline(person: Person, facts: list[Fact], names: dict[str, str]) -> Person:
    employment = [
        f for f in facts if f.person_id == person.id and f.type == "employment" and f.active
    ]
    if not employment:
        return person.model_copy(update={"headline": "职业信息待补全"})
    latest = max(employment, key=lambda f: (f.is_current, f.start_month or 0))
    prefix = "" if latest.is_current else "曾任 "
    headline = (
        f"{prefix}{names[latest.entity_id]} · {names.get(latest.role_id or '', '职位待补全')}"
    )
    return person.model_copy(update={"headline": headline})


def _entities(organizations: list[str], schools: list[str], roles: list[str]) -> list[Entity]:
    return [
        *[
            Entity(id=f"org:{i}", type="organization", name=n, aliases=[f"{n}有限公司"])
            for i, n in enumerate(organizations)
        ],
        *[Entity(id=f"school:{i}", type="school", name=n) for i, n in enumerate(schools)],
        *[Entity(id=f"role:{i}", type="role", name=n) for i, n in enumerate(roles)],
    ]


def _edge_cases(facts: list[Fact]) -> list[Fact]:
    overrides: dict[int, dict[str, str | int | bool | None]] = {
        1: dict(
            entity_id="org:0",
            role_id="role:0",
            start_month=202001,
            end_month=202212,
            is_current=False,
        ),
        2: dict(
            entity_id="org:0",
            role_id="role:1",
            start_month=202101,
            end_month=202312,
            is_current=False,
        ),
        3: dict(
            entity_id="org:0",
            role_id="role:2",
            start_month=201001,
            end_month=201512,
            is_current=False,
        ),
        4: dict(
            entity_id="org:0", role_id="role:3", start_month=None, end_month=None, is_current=False
        ),
        5: dict(
            entity_id="org:0", role_id="role:4", start_month=202211, end_month=None, is_current=True
        ),
        6: dict(entity_id="org:0", role_id="role:1", active=False),
        7: dict(entity_id="org:1", role_id="role:0"),
        11: dict(entity_id="org:0", role_id="role:0"),
    }
    result = []
    for fact in facts:
        index = int(fact.person_id.split(":")[1])
        updates = overrides.get(index, {}) if fact.type == "employment" else {}
        if fact.type == "education" and index <= 5:
            updates = {"entity_id": "school:0"}
        result.append(Fact.model_validate({**fact.model_dump(), **updates}))
    result.extend(
        [
            Fact(
                id="f:000001:repeat",
                person_id="p:000001",
                type="employment",
                entity_id="org:0",
                role_id="role:0",
                start_month=202401,
                is_current=True,
                source_system="expert",
                source_record_id="demo-repeat-1",
            ),
            Fact(
                id="f:000007:cross-role",
                person_id="p:000007",
                type="employment",
                entity_id="org:0",
                role_id="role:2",
                start_month=202001,
                end_month=202112,
                source_system="resume",
                source_record_id="demo-cross-role-7",
            ),
        ]
    )
    return result
