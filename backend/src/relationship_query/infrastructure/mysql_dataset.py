"""将已校验的独立 SQLite 快照载入全新的本机实验库，不提供覆盖或 reset。"""

from pathlib import Path
from typing import Any

from sqlalchemy import insert, inspect
from sqlalchemy.engine import Engine

from relationship_query.infrastructure.mysql import lab_url
from relationship_query.infrastructure.read_model import (
    aliases,
    dataset_meta,
    entities,
    facts,
    people,
    schema,
    sources,
)
from relationship_query.infrastructure.snapshots import (
    iter_dataset_batches,
    open_snapshot,
    validate_snapshot,
)


def import_snapshot(path: Path, target: Engine) -> dict[str, Any]:
    lab_url(target.url.render_as_string(hide_password=False))
    if not path.is_file():
        raise ValueError("SQLite 快照文件不存在")
    if inspect(target).get_table_names():
        raise ValueError("目标实验库必须为空；不覆盖、不重置已有表")
    source = open_snapshot(path)
    try:
        with source.connect() as snapshot:
            snapshot.exec_driver_sql("BEGIN")
            counts = validate_snapshot(snapshot)
            schema.create_all(target)
            with target.begin() as connection:
                first = True
                for batch in iter_dataset_batches(snapshot):
                    if first:
                        connection.execute(
                            insert(entities), [entity.model_dump() for entity in batch.entities]
                        )
                        alias_rows = [
                            dict(entity_id=e.id, name=a) for e in batch.entities for a in e.aliases
                        ]
                        if alias_rows:
                            connection.execute(insert(aliases), alias_rows)
                        version, month = batch.version, batch.reference_month
                        first = False
                    connection.execute(
                        insert(people), [p.model_dump(exclude={"sources"}) for p in batch.people]
                    )
                    connection.execute(
                        insert(sources),
                        [dict(person_id=p.id, source=s) for p in batch.people for s in p.sources],
                    )
                    if batch.facts:
                        connection.execute(
                            insert(facts), [fact.model_dump() for fact in batch.facts]
                        )
                # 完整批次成功后才发布元数据；失败不会出现可查询的半批次。
                connection.execute(
                    insert(dataset_meta), dict(id=1, version=version, reference_month=month)
                )
            return {**counts, "data_version": version, "reference_month": month}
    finally:
        source.dispose()
