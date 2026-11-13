import hashlib
import json
import random
from collections.abc import Callable, Iterator
from pathlib import Path
from time import perf_counter

from sqlalchemy import insert

from relationship_query.domain.models import Dataset, Entity, Fact, Person, Source
from relationship_query.domain.validation import require_valid_dataset
from relationship_query.infrastructure.sqlite import (
    aliases,
    dataset_meta,
    entities,
    facts,
    open_engine,
    people,
    schema,
    sources,
)
from relationship_query.settings import DEFAULT_DATABASE

REFERENCE_MONTH = 202611
PROFILE_VERSION = "scale-v1"


def benchmark_entities() -> list[Entity]:
    return [
        Entity(
            id="org:hot", type="organization", name="虚构热门集团", aliases=["虚构热门集团有限公司"]
        ),
        Entity(id="school:hot", type="school", name="虚构热门大学"),
        *[
            Entity(id=f"org:anchor-{x}", type="organization", name=f"虚构样例公司{x}")
            for x in ("a", "b")
        ],
        *[
            Entity(
                id=f"org:{i:04d}",
                type="organization",
                name=f"虚构公司{i:04d}",
                aliases=[f"虚构企业{i:04d}"],
            )
            for i in range(1000)
        ],
        *[Entity(id=f"school:{i:03d}", type="school", name=f"虚构大学{i:03d}") for i in range(100)],
        *[Entity(id=f"role:{i:02d}", type="role", name=f"模拟职位{i:02d}") for i in range(20)],
        Entity(id="role:unused", type="role", name="无任职样例职位"),
    ]


def _month(index: int) -> int:
    return (index // 12) * 100 + index % 12 + 1


def _person(index: int) -> Person:
    identity: list[Source] = ["expert"] if index % 20 == 1 else ["resume"]
    if index % 37 == 0 or index == 10:
        identity = ["expert", "resume"]
    return Person(
        id=f"p:{index:06d}",
        name=f"模拟人物{index:06d}",
        city=["上海", "北京", "杭州", "深圳"][index % 4],
        headline="固定种子虚构履历，仅供规模测试",
        sources=identity,
        active=index % 97 != 0 and index != 11,
    )


def _work(
    person: Person, index: int, company: str, role: str = "role:00", **changes: object
) -> Fact:
    values: dict[str, object] = dict(
        id=f"f:{person.id}:{index:03d}",
        person_id=person.id,
        type="employment",
        entity_id=company,
        role_id=role,
        start_month=202001,
        end_month=202212,
        source_system=person.sources[0],
        source_record_id=f"fictional:{person.id}:{index:03d}",
    )
    return Fact.model_validate({**values, **changes})


def _reserved(person: Person, index: int) -> list[Fact] | None:
    if index == 1:
        return [_work(person, 0, "org:anchor-a")]
    if index == 2:
        return [_work(person, 0, "org:anchor-a", start_month=202101, end_month=202312)]
    if index == 3:
        return []
    if index in (4, 9, 10, 11):
        first = _work(
            person,
            0,
            "org:hot",
            start_month=None if index == 9 else 202001,
            end_month=None if index == 9 else 202212,
        )
        return (
            [
                first,
                first.model_copy(
                    update={
                        "id": f"f:{person.id}:duplicate",
                        "source_system": "resume",
                        "source_record_id": "fictional:duplicate-source",
                    }
                ),
            ]
            if index == 10
            else [first]
        )
    if index == 6:
        return [
            _work(person, 0, "org:anchor-a"),
            _work(person, 1, "org:anchor-b", start_month=202201, end_month=None, is_current=True),
        ]
    if index == 7:
        return [
            _work(person, 0, "org:anchor-b", start_month=202201, end_month=None, is_current=True)
        ]
    if index == 8:
        return [
            Fact(
                id=f"f:{person.id}:school",
                person_id=person.id,
                type="education",
                entity_id="school:hot",
                source_system=person.sources[0],
                source_record_id="fictional:school-only",
            )
        ]
    if index == 12:
        return [
            _work(person, 0, "org:anchor-a", start_month=202401, end_month=None, is_current=True)
        ]
    return None


def person_facts(index: int, seed: int) -> tuple[Person, list[Fact]]:
    person = _person(index)
    reserved = _reserved(person, index)
    if reserved is not None:
        return person, reserved
    rng = random.Random((seed << 32) + index)
    jobs = 120 if index % 1000 == 5 else rng.choices([3, 5, 8, 30], weights=[70, 20, 9, 1])[0]
    result = []
    for job in range(jobs):
        company = (
            "org:hot"
            if index % 1000 == 5 or rng.random() < 0.25
            else f"org:{rng.randrange(1000):04d}"
        )
        start_index = 2010 * 12 + rng.randrange(16 * 12)
        start, end = (
            _month(start_index),
            _month(min(start_index + rng.randrange(6, 96), 2026 * 12 + 10)),
        )
        current = job == jobs - 1 and rng.random() < 0.35
        uncertainty = rng.random()
        result.append(
            _work(
                person,
                job,
                company,
                f"role:{rng.randrange(20):02d}",
                start_month=None if uncertainty < 0.12 else start,
                end_month=None if current or uncertainty < 0.18 else end,
                is_current=current,
                active=rng.random() >= 0.02,
            )
        )
    school = "school:hot" if rng.random() < 0.5 else f"school:{rng.randrange(100):03d}"
    dated = rng.random() < 0.4
    result.append(
        Fact(
            id=f"f:{person.id}:school",
            person_id=person.id,
            type="education",
            entity_id=school,
            start_month=200809 if dated else None,
            end_month=201206 if dated else None,
            source_system=person.sources[0],
            source_record_id=f"fictional:{person.id}:school",
        )
    )
    if index % 17 == 0:
        result.append(
            result[0].model_copy(
                update={
                    "id": f"f:{person.id}:duplicate",
                    "source_record_id": f"fictional:{person.id}:duplicate",
                }
            )
        )
    return person, result


def batches(size: int, seed: int, batch_size: int = 1000) -> Iterator[Dataset]:
    if size < 100 or size > 100_000 or batch_size < 1:
        raise ValueError("规模范围 100–100000，批次大小必须为正数")
    dictionary = benchmark_entities()
    for first in range(1, size + 1, batch_size):
        rows = [
            person_facts(index, seed) for index in range(first, min(first + batch_size, size + 1))
        ]
        yield require_valid_dataset(
            Dataset(
                version=f"{PROFILE_VERSION}-{size}-{seed}",
                reference_month=REFERENCE_MONTH,
                people=[person for person, _ in rows],
                entities=dictionary,
                facts=[fact for _, history in rows for fact in history],
            )
        )


def create_database(
    path: Path, size: int, seed: int = 42, *, progress: Callable[[str], None] | None = None
) -> dict[str, object]:
    if size < 100 or size > 100000 or seed < 0:
        raise ValueError("规模范围 100–100000，种子必须非负")
    if path.resolve() == DEFAULT_DATABASE.resolve():
        raise ValueError("禁止使用默认演示库作为规模测试目标")
    # 只创建新文件，失败也不覆盖已有数据库；调用者使用自己的隔离目录。
    if path.exists():
        raise FileExistsError(f"拒绝覆盖已有文件：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=False)
    started, digest = perf_counter(), hashlib.sha256()
    engine = open_engine(path)
    person_count = fact_count = 0
    try:
        schema.create_all(engine)
        dictionary = benchmark_entities()
        with engine.begin() as connection:
            connection.execute(insert(entities), [entity.model_dump() for entity in dictionary])
            connection.execute(
                insert(aliases),
                [
                    {"entity_id": entity.id, "name": alias}
                    for entity in dictionary
                    for alias in entity.aliases
                ],
            )
            digest.update(
                json.dumps([entity.model_dump() for entity in dictionary], sort_keys=True).encode()
            )
            for batch in batches(size, seed):
                connection.execute(
                    insert(people),
                    [person.model_dump(exclude={"sources"}) for person in batch.people],
                )
                connection.execute(
                    insert(sources),
                    [
                        {"person_id": person.id, "source": source}
                        for person in batch.people
                        for source in person.sources
                    ],
                )
                if batch.facts:
                    connection.execute(insert(facts), [fact.model_dump() for fact in batch.facts])
                for person in batch.people:
                    digest.update(person.model_dump_json().encode())
                for fact in batch.facts:
                    digest.update(fact.model_dump_json().encode())
                person_count += len(batch.people)
                fact_count += len(batch.facts)
                if progress and person_count % 10000 == 0:
                    progress(f"已生成 {person_count}/{size} 人、{fact_count} 条经历")
            connection.execute(
                insert(dataset_meta),
                {
                    "id": 1,
                    "version": f"{PROFILE_VERSION}-{size}-{seed}",
                    "reference_month": REFERENCE_MONTH,
                },
            )
            connection.exec_driver_sql("ANALYZE")
    finally:
        engine.dispose()
    return {
        "people": person_count,
        "facts": fact_count,
        "seed": seed,
        "profile": PROFILE_VERSION,
        "logical_sha256": digest.hexdigest(),
        "generation_ms": round((perf_counter() - started) * 1000, 2),
        "database_bytes": path.stat().st_size,
    }
