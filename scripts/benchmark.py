"""固定种子、小规模 SQLite 服务层观察；不证明生产容量。"""

import json
import platform
import statistics
import tempfile
from pathlib import Path
from time import perf_counter

from relationship_query.contracts import SearchRequest
from relationship_query.infrastructure.fixtures import make_dataset
from relationship_query.infrastructure.sqlite import (
    SQLiteRepository,
    load_dataset,
    open_engine,
)
from relationship_query.services.query import QueryService


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="relationship-bench-") as directory:
        engine = open_engine(Path(directory) / "benchmark.sqlite")
        try:
            dataset = make_dataset(size=2000)
            load_dataset(engine, dataset)
            service = QueryService(SQLiteRepository(engine))
            cases = {
                "entity_company_role": (
                    SearchRequest(organization_id="org:0", role_id="role:0"),
                    None,
                ),
                "person_overlap": (
                    SearchRequest(relation_type="same_company_overlap"),
                    "p:000001",
                ),
            }
            measurements = {}
            for name, (request, reference) in cases.items():
                durations = []
                for _ in range(30):
                    start = perf_counter()
                    service.search(request, reference)
                    durations.append((perf_counter() - start) * 1000)
                measurements[name] = {
                    "p50_ms": round(statistics.median(durations), 2),
                    "p95_ms": round(sorted(durations)[28], 2),
                    "iterations": 30,
                }
            print(
                json.dumps(
                    {
                        "warning": "本地 SQLite 小样本进程内服务调用，非 HTTP 并发压测，非生产容量结论",
                        "python": platform.python_version(),
                        "platform": platform.platform(),
                        "dataset_version": dataset.version,
                        "people": len(dataset.people),
                        "facts": len(dataset.facts),
                        "measurements": measurements,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
