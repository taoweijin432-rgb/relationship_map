import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.domain.models import Dataset
from relationship_query.infrastructure.sqlite import load_dataset, open_engine

SAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/logical-dataset.json"


def publish_stopped_snapshot(path: Path, payload: dict[str, Any]) -> None:
    engine = open_engine(path)
    try:
        load_dataset(engine, Dataset.model_validate(payload), reset=True)
    finally:
        engine.dispose()


def candidate_proofs(client: TestClient, candidate: str) -> list[dict[str, Any]]:
    response = client.get(
        "/api/v1/relations/evidence", params={"reference_id": "p:01", "candidate_id": candidate}
    )
    assert response.status_code == 200
    return response.json()["items"]


@pytest.mark.parametrize(
    "correction",
    ["invalidate_work", "correct_company", "correct_school", "upstream_person_mapping"],
)
def test_snapshot_corrections_and_restart_cursor(tmp_path: Path, correction: str) -> None:
    path = tmp_path / "snapshot.sqlite"
    before = json.loads(SAMPLE.read_text())
    after = copy.deepcopy(before)
    after["version"] = "handoff-example-v2"
    publish_stopped_snapshot(path, before)
    with TestClient(create_app(path)) as client:
        old_cursor = client.post("/api/v1/persons/search", json={"page_size": 2}).json()[
            "next_cursor"
        ]
        assert {p["relation_type"] for p in candidate_proofs(client, "p:02")} == {
            "same_company_overlap",
            "same_company",
            "same_school",
        }
        assert candidate_proofs(client, "p:07") == []
    # 上一服务生命周期已结束，才以显式 reset 发布下一份上游快照。
    by_id = {f["id"]: f for f in after["facts"]}
    if correction == "invalidate_work":
        by_id["f:02a"]["active"] = False
    elif correction == "correct_company":
        by_id["f:02a"]["entity_id"] = "org:b"
    elif correction == "correct_school":
        by_id["f:02s"]["entity_id"] = "school:y"
    else:
        by_id["f:02a"]["person_id"] = "p:07"
        by_id["f:02s"]["person_id"] = "p:07"
    publish_stopped_snapshot(path, after)
    with TestClient(create_app(path)) as client:
        assert client.get("/api/v1/meta").json()["data_version"] == "handoff-example-v2"
        rejected = client.post("/api/v1/persons/search", json={"cursor": old_cursor})
        assert rejected.status_code == 422 and rejected.json()["code"] == "INVALID_CURSOR"
        proofs = candidate_proofs(client, "p:02")
        kinds = {p["relation_type"] for p in proofs}
        if correction in ("invalidate_work", "correct_company"):
            assert kinds == {"same_school"}
            assert all(p["candidate"]["fact"]["id"] != "f:02a" for p in proofs)
        elif correction == "correct_school":
            assert kinds == {"same_company", "same_company_overlap"}
        else:
            assert proofs == []
            moved = candidate_proofs(client, "p:07")
            assert {p["relation_type"] for p in moved} == {
                "same_company",
                "same_company_overlap",
                "same_school",
            }
            assert any(
                p["candidate"]["fact"]["source_record_id"] == "demo-resume-work-02" for p in moved
            )
            # 同名人物仍保持上游给定的两个独立 ID，没有按姓名执行合并。
            assert client.get("/api/v1/persons/p:01/facts").json()["person"]["id"] == "p:01"
            assert client.get("/api/v1/persons/p:07/facts").json()["person"]["id"] == "p:07"
