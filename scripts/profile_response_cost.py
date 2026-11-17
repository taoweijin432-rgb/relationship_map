"""独立TestClient进程测量实际FastAPI序列化；不改线上路由／发布或输出人物正文。"""

import argparse
import asyncio
import copy
import json
from pathlib import Path
from time import perf_counter, process_time
from typing import Any

import fastapi.routing
from fastapi.testclient import TestClient
from relationship_query.app import create_app
from relationship_query.benchmark.resources import process_usage
from relationship_query.benchmark.response_cost import response_usage
from relationship_query.contracts import ExportResponse
from relationship_query.runtime.diagnostics import request_id


def run(release: Path, output: Path, stress_records: int = 0) -> dict[str, Any]:
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    serializations: list[dict[str, Any]] = []
    export_options: dict[str, Any] = {}
    original = fastapi.routing.serialize_response

    async def measured(**kwargs: Any) -> Any:
        if isinstance(kwargs.get("response_content"), ExportResponse):
            export_options.clear()
            export_options.update(
                {
                    key: value
                    for key, value in kwargs.items()
                    if key != "response_content"
                }
            )
        before = process_usage()
        started, cpu_started = perf_counter(), process_time()
        result = await original(**kwargs)
        elapsed, cpu = perf_counter() - started, process_time() - cpu_started
        serializations.append(
            {
                "request_id": request_id(),
                "elapsed_ms": round(elapsed * 1000, 3),
                "cpu_ms": round(cpu * 1000, 3),
                "dump_json": kwargs.get("dump_json", False),
                "result_type": type(result).__name__,
                "before": before,
                "after": process_usage(),
            }
        )
        return result

    report: dict[str, Any] = {
        "passed": False,
        "environment": "isolated-testclient-same-process-server-and-client",
        "samples": [],
    }

    def save() -> None:
        target = output / "report.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        target.chmod(0o600)

    fastapi.routing.serialize_response = measured
    try:
        app = create_app(numeric_release_store=release)
        with TestClient(app) as client:

            def call(name: str, path: str, body: dict | None = None) -> dict:
                start = perf_counter()
                response = (
                    client.get(path) if body is None else client.post(path, json=body)
                )
                duration = (perf_counter() - start) * 1000
                response.raise_for_status()
                target = output / f"{name}.json"
                target.write_bytes(response.content)
                target.chmod(0o600)
                identity = response.headers.get("x-request-id")
                measured_rows = [
                    item for item in serializations if item["request_id"] == identity
                ]
                if not identity or len(measured_rows) != 1:
                    raise RuntimeError("响应与实际序列化观测未能逐请求关联")
                data = response.json()
                report["samples"].append(
                    {
                        "name": name,
                        "request_ms": round(duration, 3),
                        **response_usage(response.content),
                        "serialization": measured_rows,
                        "items": len(data.get("items", [])),
                        "export_fact_evidence_count": sum(
                            len(item.get("facts", [])) + len(item.get("evidence", []))
                            for item in data.get("items", [])
                        )
                        if name.startswith("export-")
                        else None,
                        "after_client_receives": process_usage(),
                    }
                )
                save()
                return data

            meta = call("meta", "/api/v1/meta")
            report["dataset"] = {
                key: meta[key]
                for key in (
                    "data_version",
                    "person_display",
                    "person_count",
                    "fact_count",
                )
            }
            for size in (20, 50):
                filters = {"max_hops": 1, "page_size": size}
                page = call(
                    f"page-{size}",
                    "/api/v1/persons/p:expert:1000/relations/search",
                    filters,
                )
                if not page["items"]:
                    raise ValueError("测量样本没有候选，拒绝用空结果代表实际响应")
                exported = call(
                    f"export-{size}",
                    "/api/v1/exports/persons",
                    {
                        "reference_id": "p:expert:1000",
                        "filters": filters,
                        "data_version": meta["data_version"],
                        "expected_person_ids": [
                            item["person"]["id"] for item in page["items"]
                        ],
                    },
                )
                call(
                    f"details-{size}",
                    f"/api/v1/persons/{page['items'][0]['person']['id']}/details",
                    {"reference_id": "p:expert:1000", "filters": filters},
                )
            if stress_records:
                # 只做序列化结构压力，不调用业务查询、不作为实际人物经历或容量验收。
                payload = copy.deepcopy(exported)
                for item in payload["items"]:
                    item["evidence"], item["connection_detail"], item["facts"] = (
                        [],
                        None,
                        [],
                    )
                template = exported["items"][0]["facts"][0]
                for index in range(stress_records):
                    item = payload["items"][index % len(payload["items"])]
                    fact = copy.deepcopy(template)
                    fact["fact"].update(
                        id=f"synthetic:{index}",
                        person_id=item["person"]["id"],
                        source_record_id=f"synthetic:{index}",
                    )
                    item["facts"].append(fact)
                if not export_options:
                    raise RuntimeError("未取得实际导出路由的序列化配置")
                encoded = asyncio.run(
                    measured(**{**export_options, "response_content": payload})
                )
                if not isinstance(encoded, bytes):
                    raise TypeError("当前实际序列化路径没有返回JSON字节")
                name = f"export-{stress_records}-structural"
                target = output / f"{name}.json"
                target.write_bytes(encoded)
                target.chmod(0o600)
                report["samples"].append(
                    {
                        "name": name,
                        "sample_kind": "synthetic-serialization-only-not-business-query",
                        "export_fact_evidence_count": stress_records,
                        "serialization": [serializations[-1]],
                        **response_usage(encoded),
                    }
                )
            if any(app.state.admission.snapshot().values()):
                raise RuntimeError("响应测量后仍有在途任务")
        report["passed"] = True
    finally:
        fastapi.routing.serialize_response = original
        report["closed"] = process_usage()
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--export-stress-records", type=int, choices=(0, 5000), default=0
    )
    args = parser.parse_args()
    result = run(args.release, args.output, args.export_stress_records)
    print(json.dumps({"passed": result["passed"], "responses": len(result["samples"])}))
