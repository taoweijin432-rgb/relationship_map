"""独立模拟更新真实写入本机Nebula，核对后仅回收本次空间与只读账号。"""

import argparse
import json
import re
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any

from nebula3.Config import Config
from nebula3.gclient.net import ConnectionPool
from relationship_query.infrastructure.graph_model import read_reader
from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
)
from relationship_query.update.artifacts import (
    artifact_directory,
    load_active,
    write_json,
)
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import SourceSnapshot, UpdateError
from relationship_query.update.projection import NumericProjectionAdapter
from relationship_query.update.service import UpdateProgram
from relationship_query.update.source import ReplaySource
from relationship_query.update.store import UpdateStore
from relationship_query.update.target import NebulaTarget

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/examples"
KINDS = ("same_company", "company_overlap", "same_school", "same_major")
PEOPLE = ["p:expert:1", "p:resume:1", "p:resume:2"]


@contextmanager
def reader_session(manifest_path: Path):
    reader = read_reader(manifest_path)
    pool, session = ConnectionPool(), None
    config = Config()
    config.timeout, config.max_connection_pool_size = 15000, 1
    try:
        if not pool.init([(reader.host, reader.port)], config):
            raise RuntimeError("独立图只读连接未就绪")
        session = pool.get_session(reader.username, reader.password.get_secret_value())
        yield session
    finally:
        if session is not None:
            session.release()
        pool.close()


def expected_relations(stage: int, month: int) -> dict[str, list[dict]]:
    """针对固定虚构样例的人工预期，不调用生产关系或时间计算函数。"""
    result: dict[str, list[dict]] = {kind: [] for kind in KINDS}
    if stage in (0, 3):
        result["same_company"] = [
            {
                "source": PEOPLE[0],
                "target": PEOPLE[1 if stage == 0 else 2],
                "properties": {
                    "entity_vid": f"e:company:{1 if stage == 0 else 2}",
                    "left_fact_rank": 101,
                    "right_fact_rank": 104 if stage == 0 else 107,
                },
            }
        ]
        company = result["same_company"][0]
        result["company_overlap"] = [
            {
                **company,
                "properties": {
                    **company["properties"],
                    "overlap_start_month": 202001,
                    "overlap_end_month": month,
                },
            }
        ]
    if stage < 2:
        result["same_school"] = [
            {
                "source": PEOPLE[0],
                "target": PEOPLE[1],
                "properties": {
                    "entity_vid": "e:school:1",
                    "left_fact_rank": 102,
                    "right_fact_rank": 105,
                },
            }
        ]
    result["same_major"] = [
        {
            "source": PEOPLE[0],
            "target": PEOPLE[1],
            "properties": {
                "entity_vid": "e:major:1",
                "left_fact_rank": 103,
                "right_fact_rank": 106,
            },
        }
    ]
    return result


def verify_graph(manifest_path: Path, stage: int, month: int) -> dict:
    manifest = json.loads(manifest_path.read_text())
    space = manifest["graph"]["space"]
    ids = ",".join(json.dumps(person) for person in PEOPLE)
    with reader_session(manifest_path) as session:
        query(session, f"USE `{space}`")
        nodes = query(
            session,
            f"FETCH PROP ON person {ids} "
            "YIELD id(vertex) AS vid,properties(vertex) AS properties",
        )
        assert {row["vid"] for row in nodes} == set(PEOPLE[: 3 if stage == 3 else 2])
        for row in nodes:
            assert row["properties"] == {
                "source_system": "expert" if row["vid"] == PEOPLE[0] else "resume",
                "serial_number": row["vid"].removeprefix("p:").replace(":", "-"),
            }
        expected = expected_relations(stage, month)
        for kind in KINDS:
            actual = query(
                session,
                f"GO FROM {ids} OVER {kind} YIELD src(edge) AS source,"
                "dst(edge) AS target,properties(edge) AS properties LIMIT [101]",
            )
            assert actual == expected[kind], (stage, kind, actual)
        ranks: set[int] = set()
        for kind in ("worked_at", "studied_at", "studied_major"):
            facts = query(
                session,
                f"GO FROM {ids} OVER {kind} YIELD rank(edge) AS rank,"
                "dst(edge) AS target,properties(edge) AS properties LIMIT [101]",
            )
            ranks.update(row["rank"] for row in facts)
            if kind == "worked_at":
                expert = next(row for row in facts if row["rank"] == 101)
                assert expert["target"] == f"e:company:{1 if stage == 0 else 2}"
                assert expert["properties"]["position_title"] == (
                    "模拟工程师" if stage == 0 else "模拟技术负责人"
                )
        expected_ranks = {
            0: {101, 102, 103, 104, 105, 106},
            1: {101, 102, 103, 104, 105, 106},
            2: {101, 103, 104, 105, 106},
            3: {101, 103, 104, 105, 106, 107},
        }
        assert ranks == expected_ranks[stage]
        rejected = session.execute(
            'INSERT VERTEX person(source_system,serial_number) VALUES "p:expert:999":("expert","test")'
        )
        assert not rejected.is_succeeded(), "新图只读账号不应拥有写权限"
    return {
        "stage": stage,
        "month": month,
        "space": space,
        "facts": len(ranks),
        "relations": sum(len(rows) for rows in expected.values()),
        "guest_read_verified": True,
        "guest_write_denied": True,
    }


def cleanup(output: Path, credentials: Path) -> dict:
    """资源名仅取自本次新目录的创建意图及私有账号文件。"""
    spaces, accounts = set(), set()
    for path in output.glob("state/releases/*/*/build-resource.json"):
        space = json.loads(path.read_text())["space"]
        if not re.fullmatch(r"relationship_lab_sync_[0-9a-f]{12}", space):
            raise ValueError("资源日志空间名不符合本次实验规则")
        spaces.add(space)
    for path in output.glob("state/releases/*/*/reader-credentials.json"):
        accounts.add(read_reader(path.parent / "manifest.json").username)
    with connect(load_credentials(credentials)) as session:
        for space in sorted(spaces):
            query(session, f"DROP SPACE IF EXISTS `{space}`")
        for account in sorted(accounts):
            query(session, f"DROP USER IF EXISTS {account}")
        remaining = {row["Name"] for row in query(session, "SHOW SPACES")}
        assert not spaces & remaining
    active = output / "state/active.json"
    if active.exists():
        active.rename(active.with_name("retired-active.json"))
    return {
        "spaces_reclaimed": len(spaces),
        "accounts_reclaimed": len(accounts),
        "active_retired": True,
    }


def run(output: Path, credentials: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    report: dict[str, Any] = {
        "mode": "native-nebula-with-fictional-file-replay",
        "mysql_connected": False,
        "live_cdc": False,
        "checks": [],
        "passed": False,
    }
    try:
        contract = SourceContract.model_validate_json(
            (EXAMPLES / "update-contract-v1.json").read_text()
        )
        store = UpdateStore(output / "state", contract, create=True)
        program = UpdateProgram(store, NumericProjectionAdapter(contract))
        program.bootstrap(
            SourceSnapshot.model_validate_json(
                (EXAMPLES / "update-baseline-v1.json").read_text()
            ),
            202611,
        )
        target = NebulaTarget(credentials)
        baseline = None
        for stage, month in [
            (0, 202611),
            (1, 202611),
            (2, 202611),
            (3, 202611),
            (3, 202612),
        ]:
            if stage == 1:
                assert program.capture(
                    ReplaySource(EXAMPLES / "update-transactions-v1.jsonl")
                ) == {
                    "captured": 3,
                    "replayed": 0,
                }
            started = perf_counter()
            manifest = program.process(month, target, max_transactions=1)
            assert manifest is not None and manifest.to_seq == stage
            directory = artifact_directory(
                store.directory, manifest.batch_id, manifest.token
            )
            path = directory / "manifest.json"
            check = verify_graph(path, stage, month)
            check["elapsed_seconds"] = round(perf_counter() - started, 3)
            report["checks"].append(check)
            baseline = path if baseline is None else baseline
            active = load_active(store.directory, contract)
            assert active is not None and active[1] == manifest
            print(json.dumps(check, ensure_ascii=False), flush=True)
        assert program.process(202612, target) is None
        assert program.capture(
            ReplaySource(EXAMPLES / "update-transactions-v1.jsonl")
        ) == {
            "captured": 0,
            "replayed": 3,
        }
        verify_graph(baseline, 0, 202611)
        report.update(passed=True, exact_replay_verified=True, old_graph_unchanged=True)
    except Exception as error:
        report["error_type"] = type(error).__name__
        if isinstance(error, UpdateError):
            report["error_code"] = error.code
        raise
    finally:
        try:
            report["cleanup"] = cleanup(output, credentials)
        except Exception as error:
            report["passed"] = False
            report["cleanup_error_type"] = type(error).__name__
            raise
        finally:
            write_json(output / "report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    args = parser.parse_args()
    report = run(args.output.resolve(), args.credentials)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
