"""数字查询投影的显示字段与同经历筛选回归，图调用由原生专项验证。"""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert

from relationship_query.contracts import SearchRequest
from relationship_query.domain.models import Fact, Person
from relationship_query.infrastructure.numeric_api import NumericRepository
from relationship_query.infrastructure.numeric_read_model import query_schema, write_query_model
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.update.contract import SourceContract
from relationship_query.update.projection import NumericProjectionAdapter

EXAMPLES = Path(__file__).resolve().parents[2] / "resources/examples"


@pytest.fixture
def query_repository():
    engine = create_engine("sqlite://")
    schema, tables = query_schema()
    schema.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(tables.people),
            [
                Person(
                    id=f"p:expert:{index}",
                    name=f"虚构人物{index}",
                    city="杭州",
                    headline="工程师",
                    sources=["expert"],
                ).model_dump(exclude={"sources"})
                for index in (1, 2)
            ],
        )
        records = []
        for person, school_key, major_key in (
            (1, "education:1", "education:2"),
            (2, "education:3", "education:3"),
        ):
            for kind, entity, key in (
                ("education", "school:1", school_key),
                ("major", "major:1", major_key),
            ):
                records.append(
                    Fact(
                        id=f"{person}-{kind}",
                        person_id=f"p:expert:{person}",
                        type=kind,
                        entity_id=entity,
                        experience_key=key,
                        source_system="expert",
                        source_record_id=key,
                    ).model_dump()
                )
        connection.execute(insert(tables.facts), records)
    repository = NumericRepository.__new__(NumericRepository)
    SQLRepository.__init__(
        repository, engine, tables=tables, version="test-only", reference_month=202611
    )
    yield repository
    engine.dispose()


def test_numeric_school_and_major_require_same_education(query_repository):
    request = SearchRequest(school_ids=["school:1"], major_ids=["major:1"])
    assert query_repository.search_ids(request, None, None) == ["p:expert:2"]


def test_numeric_single_education_filter_keeps_both_people(query_repository):
    request = SearchRequest(school_ids=["school:1"])
    assert query_repository.search_ids(request, None, None) == ["p:expert:1", "p:expert:2"]


def test_numeric_sql_projection_preserves_names_serials_and_fact_fields(tmp_path):
    contract = SourceContract.model_validate_json(
        (EXAMPLES / "update-authoritative-contract-v1.json").read_text()
    )
    snapshot = json.loads((EXAMPLES / "update-baseline-v1.json").read_text())["tables"]
    del snapshot["mock.graph_expert_name_mapping"]
    for kind in ("company", "school", "major"):
        for row in snapshot[f"mock.graph_{kind}_entity"]:
            row["uuid"] = f"test-{kind}-{row['id']}"
    rows = contract.snapshot(snapshot)
    plan = NumericProjectionAdapter(contract).build(rows, 202611)
    path = tmp_path / "source.sqlite"
    write_query_model(path, contract, rows, plan, "query-test", 202611)
    engine = create_engine(f"sqlite:///{path}")
    _, tables = query_schema()
    repository = SQLRepository(engine, tables=tables)
    try:
        person = repository.person("p:expert:1")
        assert person is not None and person.name == rows["person_expert"][0]["name"]
        assert person.serial_number == rows["person_expert"][0]["serial_number"]
        views = repository.fact_views(["p:expert:1"])
        assert {view.entity.id for view in views} == {"company:1", "school:1", "major:1"}
        assert all(view.fact.experience_key for view in views)
        assert all(
            "name" not in node["properties"] for node in plan.nodes if node["type"] == "person"
        )
    finally:
        engine.dispose()
