"""独立构造固定种子的逻辑样例，不使用生产演示生成器。"""

import random
from typing import Any


def differential_dataset() -> dict[str, Any]:
    rng = random.Random(42)
    entities = [dict(id=f"org:{i}", type="organization", name=f"虚构公司{i}") for i in range(12)]
    entities += [dict(id=f"school:{i}", type="school", name=f"虚构学校{i}") for i in range(6)]
    entities += [dict(id=f"role:{i}", type="role", name=f"虚构职位{i}") for i in range(5)]
    people, facts = [], []
    for i in range(500):
        person_id = f"d:{i:04d}"
        sources = ["expert", "resume"] if i % 11 == 0 else ["expert" if i % 4 == 0 else "resume"]
        people.append(
            dict(
                id=person_id,
                name=f"虚构人物{i % 100}",
                city="虚构城市",
                headline="仅供差分验证",
                sources=sources,
                active=i % 19 != 18,
            )
        )
        jobs = []
        for j in range(rng.randint(1, 4)):
            start = rng.randint(2010, 2023) * 100 + rng.randint(1, 12)
            current = rng.random() < 0.25
            end = None if current or rng.random() < 0.2 else (start // 100 + 2) * 100 + start % 100
            job = dict(
                id=f"df:{i}:{j}",
                person_id=person_id,
                type="employment",
                entity_id=f"org:{rng.choice([0] * 10 + list(range(12)))}",
                role_id=None if rng.random() < 0.1 else f"role:{rng.randrange(5)}",
                start_month=None if rng.random() < 0.1 else start,
                end_month=end,
                is_current=current,
                active=rng.random() > 0.1,
                source_system=rng.choice(sources),
                source_record_id=f"synthetic-work-{i}-{j}",
            )
            jobs.append(job)
        facts.extend(jobs)
        if i % 17 == 0:
            facts.append(
                {
                    **jobs[0],
                    "id": f"df:{i}:duplicate",
                    "source_record_id": f"synthetic-work-{i}-duplicate",
                }
            )
        for j in range(rng.randrange(3)):
            facts.append(
                dict(
                    id=f"ds:{i}:{j}",
                    person_id=person_id,
                    type="education",
                    entity_id=f"school:{rng.randrange(6)}",
                    source_system=sources[0],
                    source_record_id=f"synthetic-school-{i}-{j}",
                    active=rng.random() > 0.1,
                )
            )
    return dict(
        version="differential-500-seed42",
        reference_month=202611,
        people=people,
        entities=entities,
        facts=facts,
    )
