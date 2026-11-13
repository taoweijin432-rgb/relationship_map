"""独立模拟快照的共享校验、只读连接和跨 SQL 引擎内容标识。"""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL, Connection, Engine

from relationship_query.domain.models import Dataset, Entity, Fact, Person
from relationship_query.domain.validation import require_valid_dataset
from relationship_query.infrastructure.read_model import (
    dataset_meta,
    entities,
    facts,
    people,
    schema,
    sources,
)


def iter_dataset_batches(connection: Connection) -> Iterator[Dataset]:
    meta = connection.execute(select(dataset_meta)).one()
    dictionary = [
        Entity.model_validate(row) for row in connection.execute(select(entities)).mappings()
    ]
    last: str | None = None
    while True:
        statement = select(people).order_by(people.c.id).limit(1000)
        if last is not None:
            statement = statement.where(people.c.id > last)
        rows = connection.execute(statement).mappings().all()
        if not rows:
            return
        ids = [row["id"] for row in rows]
        source_map: dict[str, list[str]] = {identity: [] for identity in ids}
        for row in connection.execute(select(sources).where(sources.c.person_id.in_(ids))):
            source_map[row.person_id].append(row.source)
        yield require_valid_dataset(
            Dataset(
                version=meta.version,
                reference_month=meta.reference_month,
                entities=dictionary,
                people=[
                    Person.model_validate({**row, "sources": source_map[row["id"]]}) for row in rows
                ],
                facts=[
                    Fact.model_validate(row)
                    for row in connection.execute(
                        select(facts).where(facts.c.person_id.in_(ids)).order_by(facts.c.id)
                    ).mappings()
                ],
            )
        )
        last = ids[-1]


def validate_lengths(dataset: Dataset) -> None:
    # 这些长度只是实验 DDL 约束；超长值报错，不静默截断或当作上游字段规范。
    if len(dataset.version) > 255:
        raise ValueError("数据版本超过实验长度 255")
    for group in (dataset.people, dataset.entities, dataset.facts):
        for model in group:
            for key, value in model.model_dump().items():
                values = value if isinstance(value, list) else [value]
                maximum = (
                    128 if key == "id" or key.endswith("_id") and key != "source_record_id" else 255
                )
                if any(isinstance(item, str) and len(item) > maximum for item in values):
                    raise ValueError(
                        f"{type(model).__name__} {model.id} 的 {key} 超过实验长度 {maximum}"
                    )


def validate_snapshot(source: Connection) -> dict[str, int]:
    counts = {"people": 0, "facts": 0, "sources": 0}
    for batch in iter_dataset_batches(source):
        validate_lengths(batch)
        counts["people"] += len(batch.people)
        counts["facts"] += len(batch.facts)
        counts["sources"] += sum(len(person.sources) for person in batch.people)
    for name, table in (("people", people), ("facts", facts), ("sources", sources)):
        actual = source.scalar(select(func.count()).select_from(table))
        if actual != counts[name]:
            raise ValueError(f"快照 {name} 存在未关联记录或没有人物，拒绝导入")
    if not counts["people"]:
        raise ValueError("实验快照至少需要一个人物")
    return counts


def open_snapshot(path: Path) -> Engine:
    if not path.is_file():
        raise ValueError("SQLite 快照文件不存在")
    return create_engine(
        URL.create("sqlite", database=f"file:{path.resolve()}", query={"mode": "ro", "uri": "true"})
    )


def snapshot_digest(connection: Connection) -> str:
    digest = hashlib.sha256()
    for table in schema.sorted_tables:
        digest.update(table.name.encode())
        for row in connection.execute(select(table).order_by(*table.primary_key.columns)):
            digest.update(json.dumps(list(row), sort_keys=True, ensure_ascii=False).encode())
    return digest.hexdigest()
