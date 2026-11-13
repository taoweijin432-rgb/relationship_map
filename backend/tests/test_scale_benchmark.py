from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from relationship_query.benchmark.baseline import BaselinePathRepository
from relationship_query.benchmark.cases import Case
from relationship_query.benchmark.dataset import batches, create_database, person_facts
from relationship_query.benchmark.measure import measure_case, percentile
from relationship_query.benchmark.observe import SQLTrace, capture_sql, observe_engine
from relationship_query.benchmark.report import file_digest
from relationship_query.benchmark.run import isolated_case, run
from relationship_query.contracts import PathRequest
from relationship_query.domain.path_budget import PathBudget, PathBudgetExceeded
from relationship_query.infrastructure.sqlite import SQLiteRepository, open_engine
from relationship_query.infrastructure.sqlite_paths import SQLitePathRepository
from relationship_query.runtime.diagnostics import DiagnosticTrace, capture, traced
from tests.reference_oracle import _months


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("scale") / "test.sqlite"
    create_database(path, 2000)
    return path


def test_seed_reproducibility_prefix_and_batch_validity() -> None:
    first = list(batches(100, 42, 23))
    second = list(batches(100, 42, 50))
    assert [person for batch in first for person in batch.people] == [
        person for batch in second for person in batch.people
    ]
    assert [fact for batch in first for fact in batch.facts] == [
        fact for batch in second for fact in batch.facts
    ]
    assert person_facts(85, 42) == person_facts(85, 42)
    assert person_facts(85, 42) != person_facts(85, 43)
    assert len(person_facts(5, 42)[1]) == 121
    assert person_facts(3, 42)[1] == []
    assert person_facts(10, 42)[0].sources == ["expert", "resume"]
    assert not person_facts(11, 42)[0].active


def test_database_generation_refuses_overwrite_and_invalid_input(tmp_path: Path) -> None:
    path = tmp_path / "existing.sqlite"
    path.write_bytes(b"preserve this input")
    with pytest.raises(FileExistsError):
        create_database(path, 100)
    assert path.read_bytes() == b"preserve this input"
    for size in (0, 99, 100001):
        invalid = tmp_path / f"invalid-{size}.sqlite"
        with pytest.raises(ValueError):
            create_database(invalid, size)
        assert not invalid.exists()


def test_logical_digest_is_reproducible_and_default_file_is_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relationship_query.benchmark import dataset as module

    first = create_database(tmp_path / "one.sqlite", 100)
    second = create_database(tmp_path / "two.sqlite", 100)
    assert first["logical_sha256"] == second["logical_sha256"]
    assert first["facts"] == second["facts"]
    protected = tmp_path / "protected.sqlite"
    monkeypatch.setattr(module, "DEFAULT_DATABASE", protected)
    with pytest.raises(ValueError, match="默认演示库"):
        create_database(protected, 100)
    assert not protected.exists()


def test_optional_diagnostics_preserve_values_errors_and_context() -> None:
    @traced("test")
    def compute(fail: bool = False) -> int:
        if fail:
            raise ValueError("preserved error")
        return 17

    assert compute() == 17
    outer, inner = DiagnosticTrace(), DiagnosticTrace()
    with capture(outer):
        assert compute() == 17
        with capture(inner), pytest.raises(ValueError, match="preserved error"):
            compute(True)
        assert compute() == 17
    assert outer.totals()["test"]["calls"] == 2
    assert inner.totals()["test"]["calls"] == 1
    assert compute() == 17 and len(outer.stages) == 2


def test_sql_observation_interrupt_and_cleanup(database: Path) -> None:
    engine = open_engine(database)
    trace = SQLTrace(timeout_ms=0)
    try:
        with observe_engine(engine), capture_sql(trace), engine.connect() as connection:
            with pytest.raises(OperationalError):
                connection.exec_driver_sql(
                    "WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL "
                    "SELECT x+1 FROM n WHERE x<100000) SELECT sum(x) FROM n"
                )
        assert trace.interrupted == "benchmark_sql_time_limit"
        assert trace.statements[0].failed
        with engine.connect() as connection:
            assert connection.scalar(select(1)) == 1
    finally:
        engine.dispose()


def test_path_budget_is_not_replaced_by_benchmark_observer(database: Path) -> None:
    engine = open_engine(database)
    repo = SQLiteRepository(engine)
    trace = SQLTrace(timeout_ms=0, owns_progress=False)
    try:
        with (
            observe_engine(engine),
            capture_sql(trace),
            pytest.raises(PathBudgetExceeded, match="sql_limit"),
        ):
            with SQLitePathRepository(engine, repo.version, repo.reference_month).session(
                PathBudget(3000, 100, sql_limit=1000)
            ) as reader:
                reader.connection.exec_driver_sql(
                    "WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL "
                    "SELECT x+1 FROM n WHERE x<100000) SELECT sum(x) FROM n"
                )
        assert trace.interrupted is None
        with engine.connect() as connection:
            assert connection.scalar(select(1)) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("source", [None, "expert", "resume"])
@pytest.mark.parametrize(
    "scope",
    [
        {"relation_type": "same_company_overlap"},
        {
            "relation_type": "same_company_overlap",
            "relation_start_month": 202001,
            "relation_end_month": 202212,
            "min_overlap_months": 12,
        },
        {"relation_type": "same_school"},
        {},
    ],
)
def test_candidate_strategies_preserve_full_prefix_and_order(
    database: Path, source: str | None, scope: dict
) -> None:
    engine = open_engine(database)
    repo = SQLiteRepository(engine)
    before = file_digest(database)
    try:
        for reference in ("p:000001", "p:000004", "p:000005", "p:000003"):
            request = PathRequest.model_validate(
                {
                    "reference_id": reference,
                    "candidate_id": "p:000007",
                    "scope": scope,
                    "intermediate_source": source,
                    "limits": {"candidate_limit": 500},
                }
            )
            values = []
            for implementation in (BaselinePathRepository, SQLitePathRepository):
                with implementation(engine, repo.version, repo.reference_month).session(
                    PathBudget(10000, 5000, sql_limit=50_000_000)
                ) as reader:
                    values.append(reader.candidates(request))
            assert values[0] == values[1]
            assert values[1] == sorted(set(values[1])) and len(values[1]) <= 501
            assert reference not in values[1] and "p:000007" not in values[1]
        assert before == file_digest(database)
    finally:
        engine.dispose()


def test_asgi_measurement_has_stages_plans_and_consistent_response(database: Path) -> None:
    before = file_digest(database)
    case = Case(
        "ordinary", "POST", "/api/v1/persons/search", {"organization_ids": ["org:anchor-a"]}
    )
    result = measure_case(database, case, 2, 2000)
    samples = result["samples"]
    assert len(samples) == 3
    assert result["summary"]["warm_samples"] == 2
    assert all(
        sample["sql_count"] > 0 and sample["stages"]["QueryService.search"]["calls"] == 1
        for sample in samples
    )
    assert len({sample["semantic_sha256"] for sample in samples}) == 1
    assert result["query_plans"] and all(row["plan"] for row in result["query_plans"])
    assert file_digest(database) == before


def test_percentiles_and_configuration_errors_are_not_zero(tmp_path: Path) -> None:
    assert percentile([], 0.95) is None
    assert percentile([5, 1, 3, 2, 4], 0.5) == 3
    assert percentile([5, 1, 3, 2, 4], 0.95) == 5
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        run(existing, [2000])
    output = tmp_path / "invalid"
    with pytest.raises(ValueError):
        run(output, [2000], selected=["unknown-case"])
    assert not output.exists()


def test_owned_worker_timeout_is_explicit(database: Path) -> None:
    result = isolated_case(
        database, Case("meta", "GET", "/api/v1/meta"), "current", 1, 2000, timeout=0
    )
    assert not result["ok"] and result["error"] == "harness_case_wall_timeout"


def test_complete_candidate_sets_match_independent_month_sets(tmp_path: Path) -> None:
    path = tmp_path / "complete.sqlite"
    create_database(path, 400)
    data = next(batches(400, 42))
    histories = {
        person.id: [
            fact.model_dump() for fact in data.facts if fact.person_id == person.id and fact.active
        ]
        for person in data.people
    }
    months = {fact.id: _months(fact.model_dump(), data.reference_month) for fact in data.facts}

    def connected(left: str, right: str, kind: str) -> bool:
        for a in histories[left]:
            for b in histories[right]:
                if a["entity_id"] != b["entity_id"] or a["type"] != b["type"]:
                    continue
                if kind == "same_school":
                    if a["type"] == "education":
                        return True
                    continue
                if a["type"] != "employment":
                    continue
                if kind == "same_company":
                    return True
                common = (months[a["id"]] or set()) & (months[b["id"]] or set())
                if kind == "window":
                    common = {month for month in common if 202001 <= month <= 202212}
                if len(common) >= (12 if kind == "window" else 1):
                    return True
        return False

    engine = open_engine(path)
    repo = SQLiteRepository(engine)
    try:
        for reference in ("p:000001", "p:000004"):
            for kind in ("same_company", "same_company_overlap", "same_school", "window"):
                for source in (None, "expert"):
                    scope = {"relation_type": "same_company_overlap" if kind == "window" else kind}
                    if kind == "window":
                        scope.update(
                            relation_start_month=202001,
                            relation_end_month=202212,
                            min_overlap_months=12,
                        )
                    expected = [
                        person.id
                        for person in data.people
                        if person.active
                        and person.id not in {reference, "p:000007"}
                        and (source is None or source in person.sources)
                        and connected(reference, person.id, kind)
                    ]
                    request = PathRequest.model_validate(
                        {
                            "reference_id": reference,
                            "candidate_id": "p:000007",
                            "scope": scope,
                            "intermediate_source": source,
                            "limits": {"candidate_limit": 500},
                        }
                    )
                    for implementation in (BaselinePathRepository, SQLitePathRepository):
                        with implementation(engine, repo.version, repo.reference_month).session(
                            PathBudget(10000, 5000, sql_limit=50_000_000)
                        ) as reader:
                            assert reader.candidates(request) == expected
    finally:
        engine.dispose()
