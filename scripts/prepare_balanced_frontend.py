"""从已验证MySQL初始快照建立持续供前端使用的SQL与原生图发布。"""

import argparse
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.infrastructure.nebula_lab import DEFAULT_CREDENTIALS
from relationship_query.update.artifacts import checksum, load_active, write_json
from relationship_query.update.contract import SourceContract
from relationship_query.update.projection import NumericProjectionAdapter
from relationship_query.update.service import UpdateProgram
from relationship_query.update.source import read_snapshot
from relationship_query.update.store import UpdateStore
from relationship_query.update.target import NebulaTarget

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/mysql-update-latest/run-v3-final"


def verify(directory: Path) -> dict:
    with TestClient(create_app(numeric_release_store=directory / "state")) as client:

        def call(method: str, endpoint: str, body: dict | None = None) -> dict:
            response = client.request(method, f"/api/v1{endpoint}", json=body)
            if response.status_code != 200:
                raise RuntimeError(f"{endpoint}: {response.status_code} {response.text}")
            return response.json()

        meta = call("GET", "/meta")
        assert meta["person_count"] == 262, meta
        assert meta["fact_count"] == 1055, meta
        cases = json.loads((INPUT / "manual-cases.json").read_text())
        paths = []
        for case in cases[:4]:
            result = call(
                "POST",
                "/relations/paths",
                {
                    "reference_id": case["left"],
                    "candidate_id": case["right"],
                    "limits": {"time_budget_ms": 3000},
                },
            )
            actual = [path["intermediate"]["id"] for path in result["paths"]]
            assert actual == case["middle"], (case, actual)
            paths.append({"case": case["name"], "intermediates": actual})
        filters = {"school_ids": ["school:7"], "major_ids": ["major:8"]}
        people = call("POST", "/persons/search", filters)
        assert [item["person"]["id"] for item in people["items"]] == ["p:resume:9"], people
        major = call(
            "POST", "/persons/p:expert:8/relations/search", {"relation_type": "same_major"}
        )
        assert [item["person"]["id"] for item in major["items"]] == ["p:resume:8"]
        call(
            "POST",
            "/relations/paths",
            {
                "reference_id": "p:expert:8",
                "candidate_id": "p:resume:8",
                "scope": {"relation_type": "same_major"},
                "limits": {"time_budget_ms": 3000},
            },
        )
        large = call("POST", "/persons/search", {"organization_ids": ["company:9007199254740993"]})
        assert [item["person"]["id"] for item in large["items"]] == ["p:expert:10"]
        for position, expected in (("研发工程师", ["p:expert:1"]), ("行业研究负责人", [])):
            result = call(
                "POST",
                "/persons/search",
                {
                    "organization_ids": ["company:1"],
                    "position_titles": [position],
                },
            )
            assert [item["person"]["id"] for item in result["items"]] == expected
        search = call("POST", "/persons/p:expert:1/relations/search", {})
        assert any(item["person"]["id"] == "p:resume:1" for item in search["items"])
        call("GET", "/persons/p:expert:1/facts")
        call(
            "POST", "/persons/compare", {"reference_id": "p:expert:1", "candidate_id": "p:resume:1"}
        )
        call("POST", "/graph/expand", {"person_id": "p:expert:1"})
        call(
            "POST",
            "/exports/persons",
            {
                "reference_id": "p:expert:1",
                "filters": {},
                "data_version": meta["data_version"],
                "expected_person_ids": [item["person"]["id"] for item in search["items"]],
            },
        )
        return {
            "meta": meta,
            "paths": paths,
            "same_education_row": True,
            "same_major_search_and_path": True,
            "bigint_string_identity": True,
            "same_employment_row": True,
            "related_comparison_expand_export": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--resume", action="store_true", help="核对已经构建成功的发布并完成激活")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.resume:
        contract = SourceContract.model_validate_json((output / "contract.json").read_text())
        active = load_active(output / "state", contract)
        if active is None:
            raise RuntimeError("已有目录尚无成功发布")
        release = active[1]
    else:
        output.mkdir(parents=True, exist_ok=False, mode=0o700)
        upstream = json.loads((INPUT / "report.json").read_text())
        assert upstream["passed"]
        contract_data = json.loads((INPUT / "contract.json").read_text())
        contract_data["version"] += "-query-v1"
        for table in ("person_expert", "person_resume"):
            contract_data["tables"][table]["columns"].update(city="city", headline="job_name")
        contract = SourceContract.model_validate(contract_data)
        write_json(output / "contract.json", contract.model_dump(mode="json"))
        snapshot = read_snapshot(INPUT / "baseline.json")
        store = UpdateStore(output / "state", contract, create=True)
        program = UpdateProgram(store, NumericProjectionAdapter(contract))
        program.bootstrap(snapshot, 202611)
        release = program.process(202611, NebulaTarget(DEFAULT_CREDENTIALS))
        assert release is not None and release.state == "verified"
    report = verify(output)
    report.update(
        passed=True,
        baseline_sha256=checksum(INPUT / "baseline.json"),
        source=str(INPUT.relative_to(ROOT)),
        release=release.model_dump(mode="json"),
    )
    write_json(output / "report.json", report)
    if args.activate:
        default = ROOT / "data/frontend-source.json"
        staging = default.with_suffix(".tmp")
        write_json(
            staging,
            {
                "format": "numeric-query-source-v1",
                "store": str((output / "state").relative_to(default.parent)),
            },
        )
        os.replace(staging, default)
    print(
        json.dumps(
            {"passed": True, "output": str(output), "activated": args.activate}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
