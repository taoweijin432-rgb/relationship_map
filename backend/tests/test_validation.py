import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from relationship_query.cli import main
from relationship_query.domain.models import Dataset
from relationship_query.domain.validation import DatasetValidationError, validate_payload
from relationship_query.infrastructure.sqlite import load_dataset, open_engine

SAMPLE = Path(__file__).resolve().parents[2] / "resources/examples/logical-dataset.json"


@pytest.fixture
def payload() -> dict[str, Any]:
    return json.loads(SAMPLE.read_text())


MUTATIONS = [
    ("duplicate_person", "DUPLICATE_ID"),
    ("duplicate_entity", "DUPLICATE_ID"),
    ("duplicate_fact", "DUPLICATE_ID"),
    ("missing_person", "MISSING_REFERENCE"),
    ("missing_entity", "MISSING_REFERENCE"),
    ("wrong_entity_type", "ENTITY_TYPE_MISMATCH"),
    ("wrong_role", "INVALID_ROLE_REFERENCE"),
    ("unmapped_source", "SOURCE_UNMAPPED"),
    ("invalid_month", "SCHEMA_ERROR"),
    ("inverted_interval", "SCHEMA_ERROR"),
    ("current_end", "SCHEMA_ERROR"),
    ("future_current", "INVALID_CURRENT_INTERVAL"),
    ("duplicate_source", "INVALID_SOURCES"),
    ("empty_source", "INVALID_SOURCES"),
    ("duplicate_alias", "DUPLICATE_ALIAS"),
    ("blank_alias", "EMPTY_VALUE"),
    ("empty_version", "EMPTY_VALUE"),
    ("blank_id", "EMPTY_VALUE"),
    ("empty_source_record", "EMPTY_VALUE"),
    ("education_role", "INVALID_EMPLOYMENT_FIELDS"),
    ("education_current", "INVALID_EMPLOYMENT_FIELDS"),
    ("graph_node_collision", "GRAPH_ID_COLLISION"),
    ("graph_edge_collision", "GRAPH_ID_COLLISION"),
]


def corrupt(payload: dict[str, Any], mutation: str) -> None:
    if mutation.startswith("duplicate_") and mutation.split("_")[1] in ("person", "entity", "fact"):
        group = {"person": "people", "entity": "entities", "fact": "facts"}[mutation.split("_")[1]]
        payload[group].append(copy.deepcopy(payload[group][0]))
        return
    updates = {
        "missing_person": ("person_id", "missing"),
        "missing_entity": ("entity_id", "missing"),
        "wrong_entity_type": ("entity_id", "school:x"),
        "wrong_role": ("role_id", "org:a"),
        "unmapped_source": ("source_system", "resume"),
        "invalid_month": ("start_month", 202613),
        "inverted_interval": ("start_month", 202501),
        "current_end": ("is_current", True),
        "empty_source_record": ("source_record_id", " "),
    }
    if mutation in updates:
        field, value = updates[mutation]
        payload["facts"][0][field] = value
    elif mutation == "future_current":
        payload["facts"][1]["start_month"] = 202701
    elif mutation in ("duplicate_source", "empty_source"):
        payload["people"][0]["sources"] = (
            ["expert", "expert"] if mutation == "duplicate_source" else []
        )
    elif mutation in ("duplicate_alias", "blank_alias"):
        payload["entities"][0]["aliases"] = (
            ["星澜", "星澜"] if mutation == "duplicate_alias" else [" "]
        )
    elif mutation == "empty_version":
        payload["version"] = " "
    elif mutation == "blank_id":
        payload["people"][0]["id"] = " "
    elif mutation == "education_role":
        payload["facts"][2]["role_id"] = "role:director"
    elif mutation == "education_current":
        payload["facts"][2]["is_current"] = True
    elif mutation in ("graph_node_collision", "graph_edge_collision"):
        collision_id = (
            payload["people"][0]["id"] if mutation == "graph_node_collision" else "edge:f:01a"
        )
        payload["entities"].append(
            {"id": collision_id, "type": "organization", "name": "虚构冲突实体"}
        )
    else:
        raise AssertionError(f"unknown corruption {mutation}")


@pytest.mark.parametrize("mutation,code", MUTATIONS)
def test_preflight_errors_are_located(payload: dict[str, Any], mutation: str, code: str) -> None:
    corrupt(payload, mutation)
    original = copy.deepcopy(payload)
    _, report = validate_payload(payload)
    assert not report.valid
    assert code in {issue.code for issue in report.errors}
    assert all(issue.path.startswith("/") for issue in report.errors)
    assert report.counts.error_count == len(report.errors)
    assert payload == original


def test_warnings_do_not_repair_or_merge(payload: dict[str, Any]) -> None:
    payload["entities"][1]["aliases"].append("星澜")
    original = copy.deepcopy(payload)
    dataset, report = validate_payload(payload)
    assert report.valid and dataset is not None
    assert {issue.code for issue in report.warnings} == {
        "INCOMPLETE_EMPLOYMENT_TIME",
        "POSSIBLE_DUPLICATE_FACT",
        "AMBIGUOUS_ENTITY_NAME",
    }
    assert report.counts.warning_count == len(report.warnings)
    assert report.counts.person_count == 14 and report.counts.fact_count == 29
    assert dataset.facts[7].start_month is None
    assert len(dataset.people) == 14 and len(dataset.entities) == 10
    assert payload == original


def test_same_names_across_entity_types_are_not_ambiguity(payload: dict[str, Any]) -> None:
    payload["entities"][2]["aliases"].append("星澜")
    _, report = validate_payload(payload)
    assert report.valid and not any(w.code == "AMBIGUOUS_ENTITY_NAME" for w in report.warnings)


def test_multiple_semantic_errors_are_collected(payload: dict[str, Any]) -> None:
    corrupt(payload, "duplicate_person")
    corrupt(payload, "wrong_role")
    payload["facts"][3]["person_id"] = "missing"
    _, report = validate_payload(payload)
    assert {"DUPLICATE_ID", "INVALID_ROLE_REFERENCE", "MISSING_REFERENCE"} <= {
        error.code for error in report.errors
    }


@pytest.mark.parametrize("existing", [False, True])
def test_failed_import_does_not_create_or_change_database(
    tmp_path: Path,
    payload: dict[str, Any],
    existing: bool,
) -> None:
    path = tmp_path / "import.sqlite"
    engine = open_engine(path)
    dataset = Dataset.model_validate(payload)
    if existing:
        load_dataset(engine, dataset)
    before = path.read_bytes() if existing else None
    broken = dataset.model_copy(update={"people": [*dataset.people, dataset.people[0]]})
    with pytest.raises(DatasetValidationError) as exc:
        load_dataset(engine, broken, reset=True)
    assert exc.value.report.errors[0].code == "DUPLICATE_ID"
    if existing:
        assert path.read_bytes() == before
    else:
        assert not path.exists()
    engine.dispose()


@pytest.mark.parametrize("invalid", [False, True])
def test_cli_is_read_only_with_existing_database(
    tmp_path: Path,
    payload: dict[str, Any],
    invalid: bool,
) -> None:
    path = tmp_path / "existing.sqlite"
    engine = open_engine(path)
    load_dataset(engine, Dataset.model_validate(payload))
    engine.dispose()
    if invalid:
        corrupt(payload, "missing_person")
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps(payload, ensure_ascii=False))
    before = {
        file: (hashlib.sha256(file.read_bytes()).hexdigest(), file.stat().st_mtime_ns)
        for file in (path, sample)
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "relationship_query.cli",
            "validate-dataset",
            "--input",
            str(sample),
        ],
        env={**os.environ, "RELATIONSHIP_DATABASE": str(path)},
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(result.stdout)
    assert result.returncode == (1 if invalid else 0)
    assert report["valid"] is not invalid
    assert report["data_mode"] == "mock" and report["report_version"] == "1"
    assert result.stderr == ""
    assert before == {
        file: (hashlib.sha256(file.read_bytes()).hexdigest(), file.stat().st_mtime_ns)
        for file in (path, sample)
    }


def test_preflight_never_opens_engine_or_creates_target_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "not-created" / "demo.sqlite"
    monkeypatch.setenv("RELATIONSHIP_DATABASE", str(target))
    monkeypatch.setattr(sys, "argv", ["cli", "validate-dataset", "--input", str(SAMPLE)])
    with patch(
        "relationship_query.cli.open_engine", side_effect=AssertionError("DB access forbidden")
    ):
        assert main() == 0
    assert json.loads(capsys.readouterr().out)["valid"]
    assert not target.parent.exists()


@pytest.mark.parametrize(
    "content,code",
    [(b"{", "INVALID_JSON"), (b"\xff", "INPUT_READ_ERROR"), (b"null", "SCHEMA_ERROR")],
)
def test_cli_bad_files_are_json_reports(tmp_path: Path, content: bytes, code: str) -> None:
    sample = tmp_path / "bad.json"
    sample.write_bytes(content)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "relationship_query.cli",
            "validate-dataset",
            "--input",
            str(sample),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1 and json.loads(result.stdout)["errors"][0]["code"] == code
    assert sample.read_bytes() == content


def test_existing_export_cli_remains_compatible() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "relationship_query.cli", "export-openapi"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode == 0 and json.loads(result.stdout)["info"]["title"] == "人物关系查询原型"
    )


def test_empty_logical_snapshot_does_not_insert_default_rows(tmp_path: Path) -> None:
    from relationship_query.infrastructure.sqlite import SQLiteRepository

    dataset, report = validate_payload(
        {
            "version": "empty-v1",
            "reference_month": 202611,
            "people": [],
            "entities": [],
            "facts": [],
        }
    )
    assert report.valid and dataset is not None
    engine = open_engine(tmp_path / "empty.sqlite")
    try:
        assert load_dataset(engine, dataset)
        assert SQLiteRepository(engine).counts() == {
            "person_count": 0,
            "expert_count": 0,
            "resume_count": 0,
            "entity_count": 0,
            "fact_count": 0,
        }
    finally:
        engine.dispose()
