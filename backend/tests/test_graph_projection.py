import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from relationship_query.app import create_app
from relationship_query.contracts import PathRequest
from relationship_query.domain.models import Dataset
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.graph_client import GraphClient, GraphDependencyError
from relationship_query.infrastructure.graph_model import (
    ProjectionManifest,
    ReaderCredentials,
    ids_digest,
    literal,
    read_reader,
    vid,
)
from relationship_query.infrastructure.graph_paths import GraphPathReader, GraphPathRepository
from relationship_query.infrastructure.graph_projection import project_snapshot
from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
)
from relationship_query.infrastructure.read_model import facts, people
from relationship_query.infrastructure.snapshots import open_snapshot, snapshot_digest
from relationship_query.infrastructure.sqlite import SQLiteRepository, load_dataset, open_engine
from relationship_query.infrastructure.sqlite_paths import SQLitePathRepository
from relationship_query.services.query import QueryError
from tests.differential_data import differential_dataset
from tests.reference_oracle import scoped_proofs
from tests.test_paths import _expected_paths, _signatures
from tests.test_query_baseline import GOLDEN_DATA

LIVE = pytest.mark.skipif(
    os.environ.get("RELATIONSHIP_GRAPH_TEST") != "1", reason="显式启用图投影／业务集成测试"
)


@pytest.mark.parametrize("kind", ["p", "e", "b"])
def test_vid_namespaces_and_literal_roundtrip(kind: str) -> None:
    value = '标识"\\;DELETE\n😀'
    assert json.loads(literal(vid(kind, value))) == f"{kind}|{value}"
    with pytest.raises(ValueError):
        vid(kind, "人" * 100)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "building"),
        ("format_version", 2),
        ("block_size", 0),
        ("space", "production"),
        ("source_digest", "invalid"),
    ],
)
def test_unpublished_or_other_manifest_is_rejected(field: str, value: object) -> None:
    raw = dict(
        space="relationship_lab_test",
        projection_id="p",
        data_version="v",
        reference_month=202611,
        source_digest="a" * 64,
        counts={},
    )
    with pytest.raises(ValidationError):
        ProjectionManifest.model_validate({**raw, field: value})


def test_same_version_different_sql_content_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    engine = open_engine(source)
    load_dataset(engine, Dataset.model_validate_json(GOLDEN_DATA.read_text()))
    repo = SQLiteRepository(engine)
    with engine.connect() as connection:
        digest = snapshot_digest(connection)
    manifest = ProjectionManifest(
        space="relationship_lab_test",
        projection_id="p",
        data_version=repo.version,
        reference_month=repo.reference_month,
        source_digest=digest,
        counts={},
    )
    file = tmp_path / "manifest.json"
    file.write_text(manifest.model_dump_json())
    with engine.begin() as connection:
        connection.execute(
            people.update().where(people.c.id == "p:01").values(name="上游同版本纠正")
        )
    try:
        with pytest.raises(QueryError) as error:
            GraphPathRepository(
                SQLitePathRepository(engine, repo.version, repo.reference_month), engine, file
            )
        assert error.value.code == "GRAPH_VERSION_MISMATCH"
    finally:
        engine.dispose()


def test_invalid_snapshot_does_not_contact_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import relationship_query.infrastructure.graph_projection as projection

    source = tmp_path / "invalid.sqlite"
    engine = open_engine(source)
    load_dataset(engine, Dataset.model_validate_json(GOLDEN_DATA.read_text()))
    with engine.begin() as connection:
        connection.execute(facts.update().values(person_id="missing"))
    engine.dispose()
    before = source.read_bytes()

    def forbidden(*_args, **_kwargs):
        pytest.fail("坏数据不可接触图数据库")

    monkeypatch.setattr(projection, "connect", forbidden)
    with pytest.raises(ValueError):
        project_snapshot(source, tmp_path / "output")
    assert not (tmp_path / "output").exists() and source.read_bytes() == before


class FakeGraph:
    def __init__(
        self, budget: PathBudget, groups: dict[str, list[str]], *, corrupt: bool = False
    ) -> None:
        self.budget, self.groups, self.corrupt = budget, groups, corrupt

    def fetch(self, tag: str, identities: list[str], budget: PathBudget) -> dict:
        budget.graph_request(len(identities))
        budget.graph_result(len(identities))
        result = {}
        for identity in identities:
            if tag == "person":
                result[identity] = {
                    "entities": len(self.groups),
                    "checksum": ids_digest(sorted(self.groups)),
                }
            elif tag == "entity":
                ids = self.groups[identity[2:]]
                result[identity] = {"members": len(ids), "blocks": (len(ids) + 127) // 128}
            else:
                entity, part = identity[2:].rsplit("|", 1)
                part = int(part)
                ids = self.groups[entity][part * 128 : (part + 1) * 128]
                result[identity] = {
                    "entity_id": entity,
                    "part": part,
                    "member_count": len(ids),
                    "checksum": ids_digest(ids),
                }
        return result

    def execute(self, statement: str, budget: PathBudget, maximum_rows: int) -> list[dict]:
        budget.graph_request(maximum_rows)
        if "OVER affiliated" in statement:
            result = [{"entity_id": entity, "kind": "employment"} for entity in self.groups]
        else:
            identity = json.JSONDecoder().raw_decode(statement[len("GO FROM ") :])[0]
            entity, part = identity[2:].rsplit("|", 1)
            part = int(part)
            ids = self.groups[entity][part * 128 : (part + 1) * 128]
            result = [{"person_id": person} for person in ids]
            if self.corrupt:
                result = result[:-1]
        budget.graph_result(len(result))
        return result


class FakeSQL:
    def qualify_candidates(self, request: PathRequest, ids: list[str]) -> list[str]:
        return [person for person in ids if int(person[2:]) % 3 == 0]


def test_sorted_block_merge_deduplicates_and_applies_qualification() -> None:
    groups = {
        "org:a": [f"p:{n:04d}" for n in range(500)],
        "org:b": [f"p:{n:04d}" for n in range(50, 1000)],
    }
    budget = PathBudget(10000, 5000)
    reader = GraphPathReader(FakeSQL(), FakeGraph(budget, groups), budget)
    request = PathRequest(reference_id="x", candidate_id="y", limits={"candidate_limit": 200})
    actual = reader.candidates(request)
    assert actual == [f"p:{n:04d}" for n in range(1000) if n % 3 == 0][:201]
    assert len(actual) == len(set(actual)) and budget.graph_rows < 20000


def test_incomplete_block_is_error_not_empty_candidates() -> None:
    budget = PathBudget(10000, 5000)
    reader = GraphPathReader(
        FakeSQL(), FakeGraph(budget, {"org:a": ["p:0000"]}, corrupt=True), budget
    )
    with pytest.raises(QueryError) as error:
        reader.candidates(PathRequest(reference_id="x", candidate_id="y"))
    assert error.value.code == "GRAPH_INTEGRITY"


def test_graph_budget_preserves_qualified_prefix_and_marks_incomplete() -> None:
    budget = PathBudget(10000, 5000)
    budget.graph_rows = 19000
    groups = {"org:a": [f"p:{n:04d}" for n in range(3000)]}
    reader = GraphPathReader(FakeSQL(), FakeGraph(budget, groups), budget)
    result = reader.candidates(
        PathRequest(reference_id="x", candidate_id="y", limits={"candidate_limit": 500})
    )
    assert result and result == [f"p:{n:04d}" for n in range(3000) if n % 3 == 0][: len(result)]
    assert budget.candidate_reasons == {"graph_limit"}
    assert budget.graph_rows <= 20000 and budget.graph_calls <= 256


@pytest.mark.parametrize("failure", ["timeout", "auth", "no_connection", "server"])
def test_transport_errors_release_resources_and_do_not_become_no_relationship(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from pydantic import SecretStr

    import relationship_query.infrastructure.graph_client as transport

    events = []

    class Session:
        def execute(self, _statement):
            if failure == "timeout":
                raise transport.IOErrorException(transport.IOErrorException.E_TIMEOUT, "timeout")

            class Result:
                def is_succeeded(self):
                    return False

                def error_code(self):
                    return -1008

                def error_msg(self):
                    return "fixture permission failure"

            return Result()

        def release(self):
            events.append("release")

    class Pool:
        def init(self, _addresses, _config):
            return True

        def get_session(self, _user, _password):
            if failure == "auth":
                raise transport.AuthFailedException("rejected")
            if failure == "no_connection":
                raise transport.NotValidConnectionException()
            return Session()

        def close(self):
            events.append("close")

    monkeypatch.setattr(transport, "ConnectionPool", Pool)
    manifest = ProjectionManifest(
        space="relationship_lab_fake",
        projection_id="fake",
        data_version="v",
        reference_month=202611,
        source_digest="a" * 64,
        counts={},
    )
    credentials = ReaderCredentials(username="rq_" + "a" * 12, password=SecretStr("a" * 24))
    client = GraphClient(manifest, credentials)
    expected = PathBudgetExceeded if failure == "timeout" else GraphDependencyError
    with pytest.raises(expected):
        client.execute("read only fixture", PathBudget(3000, 100), 1)
    assert events[-1] == "close"
    if failure in {"timeout", "server"}:
        assert events[0] == "release"
    assert all(client.slots.acquire(blocking=False) for _ in range(4))
    assert not client.slots.acquire(blocking=False)
    for _ in range(4):
        client.slots.release()


@contextmanager
def published_fixture(path: Path, output: Path, raw: dict):
    engine = open_engine(path)
    load_dataset(engine, Dataset.model_validate(raw))
    engine.dispose()
    manifest = project_snapshot(path, output)
    try:
        yield path, output / "manifest.json", manifest
    finally:
        with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
            query(session, f"DROP SPACE `{manifest.space}`")
            reader = read_reader(output / "manifest.json")
            query(session, f"DROP USER {reader.username}")


@pytest.fixture(scope="module")
def golden_graph(tmp_path_factory: pytest.TempPathFactory):
    if os.environ.get("RELATIONSHIP_GRAPH_TEST") != "1":
        pytest.skip("需要本机图投影集成环境")
    folder = tmp_path_factory.mktemp("graph-golden")
    with published_fixture(
        folder / "golden.sqlite", folder / "projection", json.loads(GOLDEN_DATA.read_text())
    ) as result:
        yield result


@pytest.mark.parametrize(
    "scope,source",
    [
        (scope, source)
        for scope in (
            {},
            {"relation_type": "same_company"},
            {"relation_type": "same_school"},
            {"relation_type": "same_company_overlap"},
            {"relation_type": "same_company_overlap", "min_overlap_months": 12},
            {
                "relation_type": "same_company_overlap",
                "relation_start_month": 202012,
                "relation_end_month": 202101,
                "min_overlap_months": 2,
            },
        )
        for source in (None, "expert")
    ],
)
def test_native_paths_equal_independent_evidence(
    golden_graph, scope: dict, source: str | None
) -> None:
    snapshot, file, _ = golden_graph
    with TestClient(create_app(snapshot, graph_manifest=file)) as client:
        response = client.post(
            "/api/v1/relations/paths",
            json={
                "reference_id": "p:01",
                "candidate_id": "p:07",
                "scope": scope,
                "intermediate_source": source,
            },
        )
        assert response.status_code == 200, response.text
        actual = response.json()
    expected = _expected_paths(json.loads(GOLDEN_DATA.read_text()), "p:01", "p:07", scope, source)
    assert actual["query_backend"] == "nebula" and actual["search_complete"]
    assert [p["intermediate"]["id"] for p in actual["paths"]] == [p[0] for p in expected]
    for path, (_, first, second) in zip(actual["paths"], expected):
        assert sorted(_signatures(path["segments"][0])) == sorted(first)
        assert sorted(_signatures(path["segments"][1])) == sorted(second)


def test_native_batch_incomplete_missing_member_and_dependency_errors(
    golden_graph, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, file, manifest = golden_graph
    with TestClient(create_app(snapshot, graph_manifest=file, graph_engine="candidates")) as client:
        with connect(load_credentials(DEFAULT_CREDENTIALS)) as admin:
            query(admin, f"USE `{manifest.space}`")
            query(admin, 'UPDATE VERTEX "meta|projection" SET projection.status="building"')
            try:
                response = client.post(
                    "/api/v1/relations/paths", json={"reference_id": "p:01", "candidate_id": "p:07"}
                )
                assert (
                    response.status_code == 409
                    and response.json()["code"] == "GRAPH_VERSION_MISMATCH"
                )
            finally:
                query(admin, 'UPDATE VERTEX "meta|projection" SET projection.status="ready"')
            query(
                admin,
                f"DELETE EDGE member {literal(vid('b', 'org:a', 0))}->"
                f"{literal(vid('p', 'p:01'))}@0",
            )
            try:
                response = client.post(
                    "/api/v1/relations/paths", json={"reference_id": "p:01", "candidate_id": "p:07"}
                )
                assert response.status_code == 503 and response.json()["code"] == "GRAPH_INTEGRITY"
            finally:
                query(
                    admin,
                    f"INSERT EDGE member(person_id) VALUES {literal(vid('b', 'org:a', 0))}->"
                    f'{literal(vid("p", "p:01"))}@0:("p:01")',
                )

        def failure(*_args, **_kwargs):
            raise GraphDependencyError()

        monkeypatch.setattr(client.app.state.path_service.repository.client, "execute", failure)
        response = client.post(
            "/api/v1/relations/paths", json={"reference_id": "p:01", "candidate_id": "p:07"}
        )
        assert response.status_code == 503 and response.json()["code"] == "GRAPH_UNAVAILABLE"


def test_guest_cannot_write_and_reports_not_overwritten(golden_graph) -> None:
    snapshot, file, manifest = golden_graph
    graph = GraphClient(manifest, read_reader(file))
    with pytest.raises(GraphDependencyError):
        graph.execute(
            'INSERT VERTEX person(id) VALUES "malicious":("bad")', PathBudget(3000, 100), 0
        )
    with pytest.raises(FileExistsError):
        project_snapshot(snapshot, file.parent)


@pytest.mark.parametrize(
    "correction",
    ["invalidate_work", "correct_company", "correct_school", "upstream_person_mapping"],
)
def test_native_corrections_reject_old_projection_and_cursor(
    golden_graph, tmp_path: Path, correction: str
) -> None:
    snapshot, old_manifest, _ = golden_graph
    raw = json.loads(GOLDEN_DATA.read_text())
    raw["version"] = "graph-corrected-v2"
    by_id = {fact["id"]: fact for fact in raw["facts"]}
    if correction == "invalidate_work":
        by_id["f:02a"]["active"] = False
    elif correction == "correct_company":
        by_id["f:02a"]["entity_id"] = "org:b"
    elif correction == "correct_school":
        by_id["f:02s"]["entity_id"] = "school:y"
    else:
        by_id["f:02a"]["person_id"] = "p:07"
        by_id["f:02s"]["person_id"] = "p:07"
    with TestClient(create_app(snapshot, graph_manifest=old_manifest)) as client:
        cursor = client.post("/api/v1/persons/search", json={"page_size": 2}).json()["next_cursor"]
    source = tmp_path / "corrected.sqlite"
    engine = open_engine(source)
    load_dataset(engine, Dataset.model_validate(raw))
    engine.dispose()
    with pytest.raises(QueryError) as mismatch:
        with TestClient(create_app(source, graph_manifest=old_manifest)):
            pass
    assert mismatch.value.code == "GRAPH_VERSION_MISMATCH"
    with published_fixture(tmp_path / "published.sqlite", tmp_path / "new-graph", raw) as (
        path,
        file,
        _,
    ):
        with TestClient(create_app(path, graph_manifest=file)) as client:
            rejected = client.post("/api/v1/persons/search", json={"cursor": cursor})
            assert rejected.status_code == 422 and rejected.json()["code"] == "INVALID_CURSOR"
            response = client.post(
                "/api/v1/relations/paths", json={"reference_id": "p:01", "candidate_id": "p:07"}
            )
            assert response.status_code == 200, response.text
            data = response.json()
        expected = _expected_paths(raw, "p:01", "p:07", {}, None)
        assert [p["intermediate"]["id"] for p in data["paths"]] == [p[0] for p in expected]
        direct = _signatures(data["direct"]) if data["direct"] else []
        assert sorted(direct) == sorted(scoped_proofs(raw, "p:01", "p:07", {}))


@LIVE
def test_failed_audit_never_publishes_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import relationship_query.infrastructure.graph_projection as projection

    source = tmp_path / "source.sqlite"
    engine = open_engine(source)
    load_dataset(engine, Dataset.model_validate_json(GOLDEN_DATA.read_text()))
    engine.dispose()
    before = source.read_bytes()
    output = tmp_path / "failed"

    def mismatch(*_args, **_kwargs):
        raise ValueError("injected audit mismatch")

    monkeypatch.setattr(projection, "_audit_batch", mismatch)
    with pytest.raises(ValueError, match="audit mismatch"):
        project_snapshot(source, output)
    assert not (output / "manifest.json").exists() and source.read_bytes() == before
    space = json.loads((output / "building.json").read_text())["space"]
    with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
        try:
            query(session, f"USE `{space}`")
            rows = query(
                session,
                'FETCH PROP ON projection "meta|projection" '
                "YIELD properties(vertex).status AS status",
            )
            assert rows == [{"status": "building"}]
        finally:
            query(session, f"DROP SPACE `{space}`")


@LIVE
def test_independent_500_all_candidates(tmp_path: Path) -> None:
    raw = differential_dataset()
    with published_fixture(tmp_path / "source.sqlite", tmp_path / "graph", raw) as (
        snapshot,
        file,
        manifest,
    ):
        engine = open_snapshot(snapshot)
        sql = SQLitePathRepository(engine, manifest.data_version, manifest.reference_month)
        graph = GraphPathRepository(sql, engine, file)
        try:
            for reference in ("d:0000", "d:0001", "d:0002"):
                for kind in (None, "same_company", "same_company_overlap", "same_school"):
                    for source in (None, "expert"):
                        scope = {"relation_type": kind}
                        expected = sorted(
                            person["id"]
                            for person in raw["people"]
                            if person["active"]
                            and person["id"] not in {reference, "d:0003"}
                            and (source is None or source in person["sources"])
                            and scoped_proofs(raw, reference, person["id"], scope)
                        )
                        request = PathRequest.model_validate(
                            dict(
                                reference_id=reference,
                                candidate_id="d:0003",
                                scope=scope,
                                intermediate_source=source,
                                limits={"candidate_limit": 500},
                            )
                        )
                        with graph.session(PathBudget(10000, 5000)) as reader:
                            assert reader.candidates(request) == expected
        finally:
            engine.dispose()
