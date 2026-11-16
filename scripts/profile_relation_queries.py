"""通过已部署的来源与图版本顺序核验查询，仅输出聚合耗时和计数。"""

import argparse
import json
import os
from pathlib import Path
from time import perf_counter
from typing import cast

from relationship_query.contracts import SearchRequest
from relationship_query.infrastructure.live_people import (
    LiveRealGraphRepository,
    MySQLPeople,
    open_people_engine,
)
from relationship_query.runtime.diagnostics import DiagnosticTrace, capture
from relationship_query.services.materialized_query import MaterializedQueryService
from relationship_query.services.query import QueryError
from relationship_query.update.nightly import NightlyConfig, NightlyPublisher
from relationship_query.update.source_config import MySQLSourceConfig


def profile(config_file: Path, person_id: str) -> bool:
    config = NightlyConfig.model_validate_json(config_file.read_text())
    source_file = os.environ.get("RELATIONSHIP_MYSQL_SOURCE_CONFIG")
    if not source_file:
        raise ValueError("诊断需要加载在线MySQL环境配置")
    sources = MySQLSourceConfig.read(Path(source_file))
    _, release = NightlyPublisher(config)._environment()
    engine = open_people_engine(sources, os.environ.get("RELATIONSHIP_MYSQL_INSECURE_TLS") == "1")
    repository = None
    graph = None
    try:
        started = perf_counter()
        repository = LiveRealGraphRepository(release, MySQLPeople(engine))
        repository.people.check(sources, repository.real_build.sources[1])
        graph = repository.graph_repository()
        service = MaterializedQueryService(repository, graph)
        print(
            json.dumps(
                {
                    "initialized": True,
                    "person_display": "mysql-live",
                    "data_version": repository.version,
                    "startup_ms": round((perf_counter() - started) * 1000, 2),
                }
            ),
            flush=True,
        )
        return profile_depths(service, person_id)
    finally:
        if graph is not None:
            graph.client.close()
        if repository is not None:
            repository.engine.dispose()
        engine.dispose()


def profile_depths(service: MaterializedQueryService, person_id: str) -> bool:
    passed = True
    repository = cast(LiveRealGraphRepository, service.repository)
    for depth in range(1, 5):
        trace = DiagnosticTrace()
        started = perf_counter()
        result: dict[str, object] = {"max_hops": depth}
        try:
            with capture(trace):
                repository.verify_snapshot()
                response = service.search(SearchRequest(max_hops=depth, page_size=20), person_id)
                repository.verify_snapshot()
            result.update(passed=True, items=len(response.items), has_more=response.has_more)
        except QueryError as error:
            result.update(passed=False, code=error.code)
            passed = False
        result.update(elapsed_ms=round((perf_counter() - started) * 1000, 2), stages=trace.totals())
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/relationship-map/nightly.json"))
    parser.add_argument("--person-id", default="p:expert:1000")
    args = parser.parse_args()
    return 0 if profile(args.config, args.person_id) else 1


if __name__ == "__main__":
    raise SystemExit(main())
