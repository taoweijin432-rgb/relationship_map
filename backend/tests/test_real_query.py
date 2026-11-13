"""真实发布格式的离线回归。图收据使用测试替身，原生HTTP另行验证。"""

import json
import os
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from relationship_query.infrastructure.numeric_read_model import write_query_model
from relationship_query.infrastructure.real_api import RealGraphRepository
from relationship_query.services.query import QueryError, QueryService
from relationship_query.update.artifacts import checksum, source_sqlite, write_json
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import GraphReceipt, digest
from relationship_query.update.projection import NumericProjectionAdapter

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/examples"


@pytest.fixture
def real_release(tmp_path):
    contract = SourceContract.model_validate_json(
        (EXAMPLES / "update-authoritative-contract-v1.json").read_text()
    )
    tables = json.loads((EXAMPLES / "update-baseline-v1.json").read_text())["tables"]
    del tables["mock.graph_expert_name_mapping"]
    for kind in ("company", "school", "major"):
        for row in tables[f"mock.graph_{kind}_entity"]:
            row["uuid"] = f"test-{kind}-{row['id']}"
    rows = contract.snapshot(tables)
    plan = NumericProjectionAdapter(contract).build(rows, 202611)
    version = "test-only-real-format"
    write_json(tmp_path / "contract.json", contract.model_dump(mode="json"))
    write_json(tmp_path / "source-snapshot.json", rows)
    write_json(tmp_path / "graph-plan.json", plan.model_dump(mode="json"))
    write_json(tmp_path / "input-audit.json", {})
    source_sqlite(tmp_path / "source.sqlite", contract, rows)
    write_query_model(tmp_path / "source.sqlite", contract, rows, plan, version, 202611)
    receipt = GraphReceipt(
        backend="nebula",
        space="relationship_lab_test_real",
        graph_digest="a" * 64,
        node_count=len(plan.nodes),
        fact_count=len(plan.facts),
        relation_count=0,
    )
    write_json(tmp_path / "graph-receipt.json", receipt.model_dump(mode="json"))
    (tmp_path / "graph").mkdir()
    write_json(tmp_path / "graph/build-resource.json", {"space": receipt.space})
    write_json(
        tmp_path / "graph/reader-credentials.json",
        {"username": "rq_111111111111", "password": "a" * 24},
    )
    common = dict(
        data_mode="real",
        version=version,
        source_digest=digest(rows),
        reference_month=202611,
        sources=[{"host": "fictional-entity"}, {"host": "fictional-person"}],
    )
    files = {
        name: checksum(tmp_path / name)
        for name in (
            "contract.json",
            "source-snapshot.json",
            "graph-plan.json",
            "input-audit.json",
            "source.sqlite",
        )
    }
    write_json(
        tmp_path / "prepared.json",
        dict(
            format="real-graph-plan-v1",
            **common,
            files=files,
            nodes=dict(Counter(n["type"] for n in plan.nodes)),
            facts=dict(Counter(e["type"] for e in plan.facts)),
        ),
    )
    write_json(
        tmp_path / "manifest.json",
        dict(
            format="real-graph-build-v1",
            state="verified",
            **common,
            graph=receipt.model_dump(mode="json"),
            elapsed_seconds=0.1,
            validation={
                "passed": True,
                "independent_sql_proofs": {
                    kind: {"count": 0}
                    for kind in ("same_company", "company_overlap", "same_school", "same_major")
                },
            },
        ),
    )
    return tmp_path


def test_real_repository_metadata_readonly_and_credentials(real_release):
    source = RealGraphRepository(real_release)
    try:
        assert QueryService(source).metadata()["data_mode"] == "real"
        assert source.counts()["person_count"] == 2
        assert source._graph_credentials().username == "rq_111111111111"
        with pytest.raises(OperationalError):
            with source.engine.begin() as connection:
                connection.execute(text("UPDATE demo_person SET name='test-only'"))
        source.verify_snapshot()
    finally:
        source.engine.dispose()


def test_real_startup_rejects_sql_digest_drift(real_release):
    with (real_release / "source.sqlite").open("ab") as file:
        file.write(b"test-only-drift")
    with pytest.raises(ValueError, match="摘要"):
        RealGraphRepository(real_release)


@pytest.mark.parametrize(
    "name", ["manifest.json", "input-audit.json", "graph/reader-credentials.json"]
)
def test_real_request_guard_detects_same_size_backdated_change(real_release, name):
    source = RealGraphRepository(real_release)
    try:
        path = real_release / name
        stat = path.stat()
        data = path.read_bytes()
        path.write_bytes(b" " + data[1:])
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with pytest.raises(QueryError) as error:
            source.verify_snapshot()
        assert error.value.code == "SOURCE_VERSION_MISMATCH"
    finally:
        source.engine.dispose()


def test_real_guard_detects_removed_sql(real_release):
    source = RealGraphRepository(real_release)
    try:
        (real_release / "source.sqlite").rename(real_release / "retired.sqlite")
        with pytest.raises(QueryError, match="发布已变化"):
            source.verify_snapshot()
    finally:
        source.engine.dispose()


def test_real_manifest_requires_real_mode(real_release):
    path = real_release / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["data_mode"] = "mock"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValidationError):
        RealGraphRepository(real_release)


def test_real_manifest_requires_complete_sql_proofs(real_release):
    path = real_release / "manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["validation"]["independent_sql_proofs"]["same_major"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="独立SQL"):
        RealGraphRepository(real_release)
