"""通过正常HTTP入口核对真实图查询、SQL详情与各类数据模式标识。"""

import argparse
import json
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.update.artifacts import write_json


def verify(directory: Path) -> dict:
    started = perf_counter()
    with TestClient(create_app(numeric_release_store=directory)) as client:
        startup = perf_counter() - started

        def call(method: str, endpoint: str, body: dict | None = None) -> dict:
            response = client.request(method, "/api/v1" + endpoint, json=body)
            if response.status_code != 200:
                raise RuntimeError(f"{endpoint}: {response.status_code} {response.text}")
            data = response.json()
            assert data["data_mode"] == "real", endpoint
            return data

        meta = call("GET", "/meta")
        assert (meta["person_count"], meta["fact_count"], meta["max_relation_hops"]) == (
            6525,
            25239,
            4,
        )
        call("GET", "/health")
        observations = []
        for depth in range(1, 5):
            begin = perf_counter()
            response = call(
                "POST",
                "/persons/p:expert:1076/relations/search",
                {"relation_type": "same_company", "max_hops": depth},
            )
            assert len(response["items"]) == depth
            observations.append(
                {
                    "max_hops": depth,
                    "candidate_count": len(response["items"]),
                    "elapsed_ms": round((perf_counter() - begin) * 1000, 3),
                }
            )
        filters = {"relation_type": "same_company", "max_hops": 4}
        detail = call(
            "POST",
            "/relations/evidence/search",
            {"reference_id": "p:expert:1076", "candidate_id": "p:expert:1171", "filters": filters},
        )
        assert detail["connection"]["hop_count"] == 4
        call("GET", "/persons/p:expert:1076/facts")
        call(
            "POST",
            "/persons/compare",
            {"reference_id": "p:expert:1076", "candidate_id": "p:expert:1075"},
        )
        call(
            "POST",
            "/relations/paths",
            {
                "reference_id": "p:expert:1076",
                "candidate_id": "p:expert:41256",
                "scope": {"relation_type": "same_company"},
                "limits": {"time_budget_ms": 3000},
            },
        )
        call("POST", "/graph/expand", {"person_id": "p:expert:1076", "filters": filters})
        exported = call(
            "POST",
            "/exports/persons",
            {
                "reference_id": "p:expert:1076",
                "filters": filters,
                "data_version": meta["data_version"],
                "expected_person_ids": [item["person"]["id"] for item in response["items"]],
            },
        )
        assert len(exported["items"]) == 4
        call("POST", "/persons/search", {"organization_ids": ["company:5167"], "page_size": 50})
        error = client.get("/api/v1/persons/missing/facts")
        assert error.status_code == 404 and error.json()["data_mode"] == "real"
        return dict(
            passed=True,
            meta=meta,
            startup_seconds=round(startup, 3),
            hops=observations,
            four_hop_evidence=True,
            comparison_paths_expand_export=True,
            error_data_mode=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.source.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
