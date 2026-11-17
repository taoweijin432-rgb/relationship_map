"""按已发布ID分批搜索的独立排序基准，覆盖低命中探测与实时人物变化。"""

import string

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, update

from relationship_query.domain.models import Dataset, Person
from relationship_query.domain.path_budget import shared_relation_budget
from relationship_query.infrastructure import live_people
from relationship_query.infrastructure.live_people import LiveRealGraphRepository, MySQLPeople
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.infrastructure.sqlite import load_dataset, open_engine
from relationship_query.services.query import QueryError


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    monkeypatch.setattr(live_people, "PUBLISHED_ID_BATCH", 8)
    people, raw = [], {}
    source_engine = create_engine(f"sqlite:///{tmp_path / 'source.sqlite'}")
    schema = MetaData()
    for source, name in live_people.PERSON_TABLES.items():
        table = Table(
            name,
            schema,
            Column("id", Integer, primary_key=True),
            *(
                Column(field, String)
                for field in ("name", "serial_number", "city", "job_name", "deleted_at")
            ),
        )
        schema.create_all(source_engine)
        rows = [
            dict(
                id=key,
                name=f"{'Hit' if key % 2 == 0 else 'Other'}-{source}-{key}",
                serial_number=f"QA-{key}",
                city="模拟城市",
                job_name="模拟岗位",
                deleted_at="2026-11-17" if key == 222 else None,
            )
            for key in range(1, 501)
        ]
        for key, label in {3: "100%模拟", 4: "O'Brien", 5: "école", 6: "École"}.items():
            rows[key - 1]["name"] = label
        with source_engine.begin() as connection:
            connection.execute(insert(table), rows)
        raw.update((f"p:{source}:{row['id']}", row) for row in rows)
        keys = (set(range(1, 501, 13)) | {3, 4, 5, 6}) if source == "expert" else set(range(1, 16))
        people.extend(
            Person(
                id=f"p:{source}:{key}",
                name="冻结占位",
                city="",
                headline="",
                sources=[source],
                active=key != 53,
            )
            for key in sorted(keys)
        )
    published = open_engine(tmp_path / "published.sqlite")
    load_dataset(
        published,
        Dataset(
            version="cohort-test", reference_month=202611, people=people, entities=[], facts=[]
        ),
    )
    repository = object.__new__(LiveRealGraphRepository)
    SQLRepository.__init__(repository, published)
    repository.people = MySQLPeople(source_engine)
    repository.published_sources = {"expert", "resume"}
    calls = []
    original = repository.people.suggestions

    def probe(source, keyword, after):
        calls.append(source)
        return original(source, keyword, after)

    monkeypatch.setattr(repository.people, "suggestions", probe)
    try:
        yield repository, people, raw, calls, schema
    finally:
        published.dispose()
        source_engine.dispose()


def expected(people, raw, keyword, limit):
    fold = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
    return sorted(
        person.id
        for person in people
        if person.active
        and raw[person.id]["deleted_at"] is None
        and any(
            raw[person.id][field].translate(fold).startswith(keyword.translate(fold))
            for field in ("name", "serial_number")
        )
    )[:limit]


@pytest.mark.parametrize(
    "keyword", ["Hit", "hIT", "QA-", "no-match", "100%", "O'", "é", "É", "p:expert:1"]
)
@pytest.mark.parametrize("limit", [1, 20, 50])
def test_small_blocks_and_one_probe_keep_complete_global_order(cohort, keyword, limit):
    repository, people, raw, calls, _ = cohort
    result = repository.suggest_people(keyword, limit)
    assert [person.id for person in result] == expected(people, raw, keyword, limit)
    assert len(result) == len({person.id for person in result})
    assert all(person.name == raw[person.id]["name"] for person in result)
    assert calls.count("expert") <= 1 and calls.count("resume") <= 1
    assert repository.engine.pool.checkedout() == repository.people.engine.pool.checkedout() == 0


def test_new_request_refreshes_fields_and_deletions(cohort):
    repository, people, raw, _, schema = cohort
    selected = repository.suggest_people("Hit", 50)[0]
    with repository.people.engine.begin() as connection:
        connection.execute(
            update(schema.tables["experts"])
            .where(schema.tables["experts"].c.id == int(selected.id.rsplit(":", 1)[1]))
            .values(name="Changed")
        )
    assert selected.id not in {person.id for person in repository.suggest_people("Hit", 50)}
    assert repository.suggest_people("Changed", 50)[0].id == selected.id


def test_cancelled_lookup_does_not_reset_budget_or_return_partial_people(cohort):
    repository = cohort[0]
    with shared_relation_budget() as budget:
        budget.cancel()
        with pytest.raises(QueryError) as error:
            repository.suggest_people("Hit", 50)
    assert error.value.code == "PERSON_QUERY_LIMIT"
