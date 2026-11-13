"""查询改造的回归边界：稀疏过滤翻页、独立取证配额及原子漂移标记。"""

import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from relationship_query.app import create_app
from relationship_query.contracts import RelationScope, SearchRequest
from relationship_query.domain.models import Dataset, Entity, Fact, Person
from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.projection_source_trial import open_projection_engine
from relationship_query.infrastructure.source_read_model import snapshot, source_digest
from relationship_query.infrastructure.source_releases import read_bundle
from relationship_query.infrastructure.sql_release_guard import verify
from relationship_query.infrastructure.sql_repository import SQLRepository
from relationship_query.infrastructure.sqlite import load_dataset, open_engine
from relationship_query.infrastructure.uuid_api import UUIDRepository
from relationship_query.infrastructure.uuid_source import NAMES, reflect
from relationship_query.services.materialized_query import MaterializedQueryService
from relationship_query.services.query import QueryError, QueryService


class PagedGraph:
    def __init__(self, ids):
        self.ids, self.positions = sorted(ids), []

    @contextmanager
    def candidate_session(self, budget):
        yield

    def neighbor_page(self, reference, scope, after, budget):
        self.positions.append(after)
        return [identity for identity in self.ids if after is None or identity > after][:129]


@pytest.fixture
def paged_repository(tmp_path):
    ids = [f"p:resume:{i:06d}" for i in range(1, 1140)]
    people = [Person(id="p:expert:1", name="模拟中心", city="", headline="", sources=["expert"])]
    people.extend(
        Person(
            id=identity,
            name="模拟候选",
            city="",
            headline="",
            sources=["resume"],
            active=identity != ids[1000],
        )
        for identity in ids
    )
    facts = [
        Fact(
            id=f"late:{i}",
            person_id=identity,
            type="employment",
            entity_id="org:late",
            source_system="resume",
            source_record_id=f"mock:{i}",
        )
        for i, identity in enumerate(ids[1100:])
    ]
    engine = open_engine(tmp_path / "paging.sqlite")
    load_dataset(
        engine,
        Dataset(
            version="paging-v1",
            reference_month=202611,
            people=people,
            entities=[Entity(id="org:late", type="organization", name="模拟公司")],
            facts=facts,
        ),
    )
    repository = UUIDRepository.__new__(UUIDRepository)
    SQLRepository.__init__(repository, engine)
    repository.graph = PagedGraph(ids)
    yield repository, ids
    engine.dispose()


@pytest.mark.parametrize("sparse", [False, True])
def test_graph_cursor_crosses_1000_and_sparse_background_pages(paged_repository, sparse):
    repository, ids = paged_repository
    request = SearchRequest(organization_ids=["org:late"] if sparse else [], page_size=17)
    found, after = [], None
    while True:
        page = repository.search_ids(request, "p:expert:1", after)
        found.extend(page[:17])
        if len(page) <= 17:
            break
        after = page[16]
    expected = ids[1100:] if sparse else [identity for identity in ids if identity != ids[1000]]
    assert found == expected
    assert len(found) == len(set(found))
    assert len(repository.graph.positions) > 8


def test_new_query_policy_rejects_prior_cursor(paged_repository):
    repository, _ = paged_repository
    filters = SearchRequest()
    old = QueryService(repository)._fingerprint(filters, "p:expert:1")
    service = MaterializedQueryService(repository, object())
    current = service._fingerprint(filters, "p:expert:1")
    with pytest.raises(QueryError, match="游标"):
        service._decode_cursor(service._encode_cursor("p:resume:000017", old), current)


@pytest.fixture(scope="module")
def guarded_native():
    selected = os.environ.get("RELATIONSHIP_UUID_QUERY_TEST_DIR")
    if not selected:
        pytest.skip("需显式选择独立轻量校验快照")
    bundle = read_bundle(Path(selected))
    assert bundle.manifest.format_version == 4
    with TestClient(
        create_app(
            source_manifest=bundle.directory / "manifest.json", source_mysql_url=bundle.mysql_url
        )
    ) as client:
        yield client, bundle


def test_native_request_does_not_read_source_snapshot(guarded_native, monkeypatch):
    client, _ = guarded_native

    def forbidden(*args, **kwargs):
        raise AssertionError("Whole source snapshot read during a request")

    monkeypatch.setattr("relationship_query.infrastructure.uuid_api.snapshot", forbidden)
    response = client.post("/api/v1/persons/p:expert:1/relations/search", json={})
    assert response.status_code == 200, response.text


def test_native_union_preserves_each_pair_limit(guarded_native):
    client, _ = guarded_native
    graph = client.app.state.query_service.graph
    pairs = [("p:expert:1", "p:resume:3"), ("p:expert:1", "p:resume:4")]
    with graph.graph_session(PathBudget(3000, 5000)) as reader:
        proofs = reader.read_proofs(RelationScope(relation_type="same_company"), pairs, 1)
    assert [(p.left_person, p.right_person) for p in proofs] == pairs


def test_native_sql_account_cannot_write_or_truncate(guarded_native):
    _, bundle = guarded_native
    engine = open_projection_engine(bundle.mysql_url, writable=True)
    try:
        for statement in (
            "UPDATE experts SET name=name WHERE id=1",
            "TRUNCATE TABLE experts",
            "DROP TRIGGER rq_guard_0_insert",
        ):
            with engine.connect() as connection, pytest.raises(SQLAlchemyError):
                connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def mutation_native():
    selected = os.environ.get("RELATIONSHIP_UUID_MUTATION_TEST_DIR")
    if not selected:
        pytest.skip("需显式选择仅供破坏演练的隔离快照")
    directory = Path(selected)
    assert "mutation" in directory.name
    bundle = read_bundle(directory)
    # This single exported value was generated by our local lab tool; never execute the file.
    import shlex

    tokens = shlex.split((directory / "admin.env").read_text())
    assert len(tokens) == 2 and tokens[0] == "export"
    key, url = tokens[1].split("=", 1)
    assert key == "RELATIONSHIP_PROJECTION_SOURCE_MYSQL_URL"
    engine = open_projection_engine(url, writable=True)
    schema = reflect(engine)
    with TestClient(
        create_app(source_manifest=directory / "manifest.json", source_mysql_url=bundle.mysql_url)
    ) as client:
        yield client, bundle.manifest, engine, schema
    engine.dispose()


def test_native_all_36_dml_markers_rollback_atomically(mutation_native):
    _, manifest, engine, schema = mutation_native
    with engine.connect() as connection:
        digest = source_digest(snapshot(connection, schema, NAMES))
    for name in NAMES:
        table = schema.tables[name]
        for operation in ("insert", "update", "delete"):
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    row = dict(connection.execute(select(table).limit(1)).mappings().one())
                    if operation == "insert":
                        row["id"] = str(uuid4()) if isinstance(row["id"], str) else 999000001
                        if "serial_number" in row:
                            row["serial_number"] = "t" + uuid4().hex[:18]
                        statement = insert(table).values(**row)
                    elif operation == "update":
                        statement = (
                            update(table).where(table.c.id == row["id"]).values(id=row["id"])
                        )
                    else:
                        statement = delete(table).where(table.c.id == row["id"])
                    connection.execute(statement)
                    with pytest.raises(QueryError) as error:
                        verify(connection, manifest)
                    assert error.value.code == "SOURCE_VERSION_MISMATCH"
                finally:
                    transaction.rollback()
            with engine.connect() as connection:
                verify(connection, manifest)
    with engine.connect() as connection:
        assert source_digest(snapshot(connection, schema, NAMES)) == digest


def test_native_committed_change_is_rejected(mutation_native):
    client, _, engine, schema = mutation_native
    assert client.get("/api/v1/meta").status_code == 200
    with engine.begin() as connection:
        connection.execute(
            update(schema.tables["experts"])
            .where(schema.tables["experts"].c.id == 1)
            .values(name="模拟已提交纠正")
        )
    response = client.get("/api/v1/meta")
    assert response.status_code == 409
    assert response.json()["code"] == "SOURCE_VERSION_MISMATCH"


def test_native_1100_complete_pagination():
    selected = os.environ.get("RELATIONSHIP_UUID_SCALE_TEST_DIR")
    if not selected:
        pytest.skip("需显式选择1100星形规模快照")
    bundle = read_bundle(Path(selected))
    with TestClient(
        create_app(
            source_manifest=bundle.directory / "manifest.json", source_mysql_url=bundle.mysql_url
        )
    ) as client:
        cursor, found = None, []
        while True:
            response = client.post(
                "/api/v1/persons/p:expert:1/relations/search",
                json=dict(page_size=50, relation_type="same_company", cursor=cursor),
            )
            assert response.status_code == 200, response.text
            page = response.json()
            found.extend(item["person"]["id"] for item in page["items"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]
        assert found == sorted(f"p:resume:{i}" for i in range(2, 1102))
        response = client.post(
            "/api/v1/persons/p:expert:1/relations/search",
            json=dict(position_titles=["入选职位"], relation_type="same_company", page_size=50),
        )
        assert response.status_code == 200, response.text
        expected = sorted(f"p:resume:{index + 2}" for index in range(1100) if index % 17 == 0)
        first = response.json()
        assert [item["person"]["id"] for item in first["items"]] == expected[:50]
        assert first["has_more"]
        response = client.post(
            "/api/v1/persons/p:expert:1/relations/search",
            json=dict(
                position_titles=["入选职位"],
                relation_type="same_company",
                page_size=50,
                cursor=first["next_cursor"],
            ),
        )
        assert response.status_code == 200, response.text
        assert [item["person"]["id"] for item in response.json()["items"]] == expected[50:]
        assert not response.json()["has_more"]
