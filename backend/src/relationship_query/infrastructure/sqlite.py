"""本地 SQLite 接入；历史导入名称保持兼容。"""

from pathlib import Path

from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.engine import Engine

from relationship_query.domain.models import Dataset
from relationship_query.domain.validation import require_valid_dataset
from relationship_query.infrastructure.read_model import (
    aliases,
    dataset_meta,
    entities,
    facts,
    people,
    schema,
    sources,
)
from relationship_query.infrastructure.sql_deadlines import DeadlineQueuePool, install_sql_deadlines
from relationship_query.infrastructure.sql_repository import SQLRepository

__all__ = [
    "SQLiteRepository",
    "aliases",
    "dataset_meta",
    "entities",
    "facts",
    "people",
    "schema",
    "sources",
    "load_dataset",
    "open_engine",
]
SQLiteRepository = SQLRepository


def open_engine(path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}, poolclass=DeadlineQueuePool
    )
    install_sql_deadlines(engine)
    return engine


def load_dataset(engine: Engine, dataset: Dataset, *, reset: bool = False) -> bool:
    dataset = require_valid_dataset(dataset)
    schema.create_all(engine)
    with engine.begin() as connection:
        existing = connection.execute(select(dataset_meta)).first()
        if existing and not reset:
            if existing.version != dataset.version:
                raise ValueError("已有不同版本数据，请显式 reset 或改用另一数据库文件")
            return False
        for table in (facts, sources, aliases, entities, people, dataset_meta):
            connection.execute(delete(table))
        if dataset.people:
            connection.execute(
                insert(people), [p.model_dump(exclude={"sources"}) for p in dataset.people]
            )
            connection.execute(
                insert(sources),
                [dict(person_id=p.id, source=s) for p in dataset.people for s in p.sources],
            )
        if dataset.entities:
            connection.execute(insert(entities), [e.model_dump() for e in dataset.entities])
        alias_rows = [dict(entity_id=e.id, name=a) for e in dataset.entities for a in e.aliases]
        if alias_rows:
            connection.execute(insert(aliases), alias_rows)
        if dataset.facts:
            connection.execute(insert(facts), [f.model_dump() for f in dataset.facts])
        connection.execute(
            insert(dataset_meta),
            dict(id=1, version=dataset.version, reference_month=dataset.reference_month),
        )
    return True
