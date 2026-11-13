import hashlib
import json
import logging
import math
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi.testclient import TestClient

from relationship_query.app import create_app
from relationship_query.benchmark.baseline import BaselinePathRepository
from relationship_query.benchmark.cases import Case
from relationship_query.benchmark.observe import SQLTrace, capture_sql, explain, observe_engine
from relationship_query.contracts import SearchRequest
from relationship_query.runtime.diagnostics import DiagnosticTrace, capture
from relationship_query.services.paths import PathService


def _shape(data: dict[str, Any]) -> dict[str, object]:
    graph = data.get("graph", {})
    items = data.get("items", [])
    evidence = data.get("evidence", data.get("items", []) if "candidate" in data else [])
    return {
        "items": len(items),
        "graph_nodes": len(graph.get("nodes", [])),
        "graph_edges": len(graph.get("edges", [])),
        "graph_truncated": graph.get("truncated"),
        "evidence": len(evidence),
        "has_more": data.get("has_more"),
        "path_status": data.get("status"),
        "path_count": len(data.get("paths", [])),
        "search_complete": data.get("search_complete"),
        "truncation_reasons": data.get("truncation_reasons", []),
        "path_stats": data.get("stats"),
        "error_code": data.get("code"),
        "query_backend": data.get("query_backend"),
    }


def percentile(values: list[float], fraction: float) -> float | None:
    return (
        round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 3) if values else None
    )


def measure_case(
    path: Path,
    case: Case,
    repeats: int,
    sql_timeout_ms: int,
    strategy: str = "current",
    *,
    mysql_url: str | None = None,
    graph_manifest: Path | None = None,
) -> dict[str, object]:
    # TestClient 经过真实路由和序列化，但不包含套接字、网关或并发负载。
    samples: list[dict[str, Any]] = []
    plans: list[dict[str, object]] = []
    if mysql_url and strategy != "current":
        raise ValueError("冻结的 baseline 仅用于 SQLite")
    app = create_app(
        None if mysql_url else path, mysql_url=mysql_url, graph_manifest=graph_manifest
    )
    startup_started = perf_counter()
    with TestClient(app) as client:
        startup_ms = (perf_counter() - startup_started) * 1000
        engine = app.state.query_service.repository.engine
        if strategy == "baseline":
            repository = app.state.query_service.repository
            app.state.path_service = PathService(
                BaselinePathRepository(engine, repository.version, repository.reference_month),
                app.state.query_service,
            )
        body = dict(case.body or {})
        if case.after:
            query = app.state.query_service
            filters = SearchRequest.model_validate(body)
            body["cursor"] = query._encode_cursor(case.after, query._fingerprint(filters, None))
        with observe_engine(engine):
            for index in range(repeats + 1):
                stages = DiagnosticTrace()
                sql = SQLTrace(
                    timeout_ms=sql_timeout_ms, owns_progress=not case.name.startswith("path_")
                )
                started = perf_counter()
                with capture(stages), capture_sql(sql):
                    response = client.request(
                        case.method, case.path, json=body if case.method == "POST" else None
                    )
                elapsed = (perf_counter() - started) * 1000
                decode_started = perf_counter()
                decoded = response.json()
                decode_ms = (perf_counter() - decode_started) * 1000
                if not isinstance(decoded, dict):
                    raise ValueError("接口响应应为 JSON 对象")
                semantic = (
                    {
                        key: decoded.get(key)
                        for key in (
                            "scope",
                            "intermediate_source",
                            "reference",
                            "candidate",
                            "direct",
                            "paths",
                        )
                    }
                    if case.name.startswith("path_")
                    else decoded
                )
                samples.append(
                    {
                        "iteration": index,
                        "phase": "first_observed" if index == 0 else "warm",
                        "http_ms": round(elapsed, 3),
                        "client_json_decode_ms": round(decode_ms, 3),
                        "status_code": response.status_code,
                        "response_bytes": len(response.content),
                        "semantic_sha256": hashlib.sha256(
                            json.dumps(semantic, sort_keys=True, ensure_ascii=False).encode()
                        ).hexdigest(),
                        "path_signatures": {
                            path["id"]: hashlib.sha256(
                                json.dumps(path, sort_keys=True).encode()
                            ).hexdigest()
                            for path in decoded.get("paths", [])
                        },
                        "response_sha256": hashlib.sha256(response.content).hexdigest()
                        if not case.name.startswith("path_")
                        else None,
                        "server_timing": response.headers.get("server-timing"),
                        "stages": stages.totals(),
                        "sql_count": len(sql.statements),
                        "cursor_execute_ms": round(
                            sum(row.elapsed_ms for row in sql.statements), 3
                        ),
                        "vm_steps_estimate": sql.vm_steps_estimate
                        if sql.owns_progress and not mysql_url
                        else None,
                        "harness_interruption": sql.interrupted,
                        "result": _shape(decoded),
                    }
                )
                if index == 0:
                    plans = explain(engine, sql.statements)
                if response.status_code >= 400:
                    break
    warm = [sample for sample in samples[1:] if sample["status_code"] == 200]
    durations = [sample["http_ms"] for sample in warm]
    reasons = Counter(
        reason for sample in samples for reason in sample["result"]["truncation_reasons"]
    )
    return {
        "case": asdict(case),
        "strategy": strategy,
        "startup_ms": round(startup_ms, 3),
        "requested_warm_repeats": repeats,
        "samples": samples,
        "summary": {
            "warm_samples": len(warm),
            "p50_ms": percentile(durations, 0.5),
            "p95_ms": percentile(durations, 0.95),
            "max_ms": max(durations) if durations else None,
            "limited_path_samples": sum(
                bool(sample["result"]["truncation_reasons"]) for sample in samples
            ),
            "truncation_reasons": dict(reasons),
            "search_incomplete_samples": sum(
                sample["result"]["search_complete"] is False for sample in samples
            ),
            "errors": sum(sample["status_code"] != 200 for sample in samples),
        },
        "query_plans": plans,
    }


def worker(
    connection: Any,
    database: str,
    case: Case,
    repeats: int,
    sql_timeout_ms: int,
    strategy: str,
    mysql_url: str | None = None,
    graph_manifest: str | None = None,
) -> None:
    try:
        logging.getLogger("relationship_query").setLevel(logging.CRITICAL)
        connection.send(
            {
                "ok": True,
                "result": measure_case(
                    Path(database),
                    case,
                    repeats,
                    sql_timeout_ms,
                    strategy,
                    mysql_url=mysql_url,
                    graph_manifest=Path(graph_manifest) if graph_manifest else None,
                ),
            }
        )
    except Exception as exc:
        # 子进程边界返回显式失败，不能让父进程把异常当成零耗时或空结果。
        connection.send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        connection.close()
