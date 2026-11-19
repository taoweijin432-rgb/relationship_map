"""读取实际MySQL人物搜索计划、扫描算子与发布成员过滤，不改来源表或索引。"""

import argparse
import getpass
import json
import os
from pathlib import Path

from relationship_query.benchmark.people_search import profile
from relationship_query.infrastructure.live_people import (
    LiveRealGraphRepository,
    MySQLPeople,
    open_people_engine,
)
from relationship_query.update.nightly import NightlyConfig, NightlyPublisher
from relationship_query.update.source_config import MySQLSourceConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-config", type=Path)
    parser.add_argument("--config", type=Path, default=Path("/etc/relationship-map/nightly.json"))
    parser.add_argument("--release", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keyword", action="append")
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 51))
    parser.add_argument("--prompt-password", action="store_true")
    parser.add_argument("--insecure-tls", action="store_true")
    args = parser.parse_args()
    keywords = args.keyword or ["张", "王", "A", "DR"]
    if len(keywords) > 16 or any(not 1 <= len(word) <= 100 for word in keywords):
        parser.error("最多诊断16个非空关键词，每个长度1至100")
    source_file = args.source_config or os.environ.get("RELATIONSHIP_MYSQL_SOURCE_CONFIG")
    if not source_file:
        parser.error("需要--source-config或在线MySQL配置环境")
    sources = MySQLSourceConfig.read(Path(source_file))
    variable = sources.endpoint("people").password_env
    if args.prompt_password:
        if variable is None:
            parser.error("人物连接须声明password_env")
        if not os.environ.get(variable):
            os.environ[variable] = getpass.getpass("People MySQL password: ")
    release = args.release
    if release is None:
        config = NightlyConfig.model_validate_json(args.config.read_text())
        _, release = NightlyPublisher(config)._environment()
    engine = open_people_engine(
        sources, args.insecure_tls or os.environ.get("RELATIONSHIP_MYSQL_INSECURE_TLS") == "1"
    )
    repository = None
    try:
        repository = LiveRealGraphRepository(release, MySQLPeople(engine))
        repository.people.check(sources, repository.real_build.sources[1])
        report = profile(repository, keywords, args.limit)
        failed = any(
            not row["passed"] or any("error" in plan for plan in row["plans"].values())
            for row in report["queries"]
        )
        report["passed"] = not failed
        args.output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        args.output.chmod(0o600)
        print(
            json.dumps(
                {
                    "profiled": True,
                    "passed": not failed,
                    "data_version": repository.version,
                    "queries": len(report["queries"]),
                    "output": str(args.output),
                }
            )
        )
        return int(failed)
    finally:
        if repository is not None:
            repository.close_query_index()
            repository.engine.dispose()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
