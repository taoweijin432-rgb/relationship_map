"""将已核对的数字来源及事实写入配套SQL读模型，关系由图提供。"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert

from relationship_query.domain.models import Entity, Fact, Person
from relationship_query.infrastructure import read_model
from relationship_query.infrastructure.read_model import QueryTables
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import Projection, Row, UpdateError, digest


def query_schema() -> tuple[MetaData, QueryTables]:
    schema = MetaData()
    tables = {
        name: getattr(read_model, name).to_metadata(schema)
        for name in ("people", "sources", "entities", "aliases", "facts", "dataset_meta")
    }
    tables["people"].append_column(Column("serial_number", String))
    for name in ("experience_key", "position_title", "education_level", "is_regular_enrollment"):
        tables["facts"].append_column(Column(name, String))
    Table(
        "numeric_query_meta",
        schema,
        Column("format_version", Integer, primary_key=True),
        Column("contract_digest", String, nullable=False),
        Column("source_digest", String, nullable=False),
    )
    return schema, QueryTables(
        **{key: tables[key] for key in ("people", "sources", "entities", "aliases", "facts")}
    )


def write_query_model(
    path: Path,
    contract: SourceContract,
    rows: dict[str, list[Row]],
    projection: Projection,
    version: str,
    reference_month: int,
) -> None:
    schema, tables = query_schema()
    nodes = {str(node["vid"]): node for node in projection.nodes}
    facts = [_fact(edge) for edge in projection.facts]
    people = _people(contract, rows, nodes, facts)
    schools = {f"e:school:{row['id']}": row for row in rows["school"]}
    entities = [
        _entity(node, schools.get(str(node["vid"]), {}).get("former_names"))
        for node in nodes.values()
        if node["type"] != "person"
    ]
    engine = create_engine(f"sqlite:///{path}")
    try:
        schema.create_all(engine)
        with engine.begin() as connection:
            if people:
                connection.execute(
                    insert(tables.people), [p.model_dump(exclude={"sources"}) for p in people]
                )
                connection.execute(
                    insert(tables.sources),
                    [
                        {"person_id": person.id, "source": source}
                        for person in people
                        for source in person.sources
                    ],
                )
            if entities:
                connection.execute(
                    insert(tables.entities), [entity.model_dump() for entity in entities]
                )
                alias_rows = [
                    {"entity_id": entity.id, "name": name}
                    for entity in entities
                    for name in entity.aliases
                ]
                if alias_rows:
                    connection.execute(insert(tables.aliases), alias_rows)
            if facts:
                connection.execute(insert(tables.facts), [fact.model_dump() for fact in facts])
            connection.execute(
                insert(schema.tables["demo_dataset"]),
                {
                    "id": 1,
                    "version": version,
                    "reference_month": reference_month,
                },
            )
            connection.execute(
                insert(schema.tables["numeric_query_meta"]),
                {
                    "format_version": 1,
                    "contract_digest": contract.fingerprint,
                    "source_digest": digest(rows),
                },
            )
    finally:
        engine.dispose()


def _people(
    contract: SourceContract, rows: dict[str, list[Row]], nodes: dict[str, Row], facts: list[Fact]
) -> list[Person]:
    current = {fact.person_id: fact.position_title for fact in facts if fact.is_current}
    result = []
    for source, table in contract.people.items():
        for row in rows[table]:
            identity = f"p:{source}:{row['id']}"
            if identity not in nodes:
                continue
            result.append(
                Person.model_validate(
                    {
                        "id": identity,
                        "name": row["name"],
                        "city": row.get("city") or "",
                        "headline": row.get("headline") or current.get(identity) or "",
                        "sources": [source],
                        "serial_number": row["serial_number"],
                    }
                )
            )
    return result


def _entity(node: Row, former_names: object = None) -> Entity:
    properties: Any = node["properties"]
    return Entity.model_validate(
        {
            "id": str(node["vid"]).removeprefix("e:"),
            "type": "organization" if node["type"] == "company" else node["type"],
            "name": properties["name"],
            "aliases": _school_aliases(former_names, properties["name"]),
        }
    )


def _school_aliases(value: object, standard_name: str) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise UpdateError(
                "INVALID_ALIASES", "学校former_names需要JSON字符串数组或NULL"
            ) from None
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(name, str) for name in value):
        raise UpdateError("INVALID_ALIASES", "学校former_names需要JSON字符串数组或NULL")
    return sorted({name.strip() for name in value if name.strip()} - {standard_name})


def _fact(edge: Row) -> Fact:
    properties: Any = edge["properties"]
    source, record = properties["experience_key"].split(":", 1)
    return Fact.model_validate(
        {
            "id": f"slot:{edge['rank']}",
            "person_id": edge["source"],
            "type": {
                "worked_at": "employment",
                "studied_at": "education",
                "studied_major": "major",
            }[str(edge["type"])],
            "entity_id": str(edge["target"]).removeprefix("e:"),
            "source_system": source,
            "source_record_id": record,
            "experience_key": properties["experience_key"],
            "start_month": properties["start_month"],
            "end_month": properties["end_month"],
            "is_current": properties.get("is_current", False),
            "position_title": properties.get("position_title"),
            "education_level": properties.get("education_level"),
            "is_regular_enrollment": properties.get("is_regular_enrollment"),
        }
    )
