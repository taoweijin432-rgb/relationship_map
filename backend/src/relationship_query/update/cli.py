"""独立命令入口。默认文件回放与计划生成，显式publish才连接本机Nebula。"""

import argparse
import json
import sqlite3
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from relationship_query.domain.models import Month
from relationship_query.update.artifacts import load_active
from relationship_query.update.contract import SourceContract
from relationship_query.update.models import UpdateError
from relationship_query.update.projection import NumericProjectionAdapter
from relationship_query.update.service import UpdateProgram
from relationship_query.update.source import ReplaySource, read_snapshot
from relationship_query.update.store import UpdateStore
from relationship_query.update.target import NebulaTarget


def main() -> int:
    parser = argparse.ArgumentParser(description="独立全量／CDC事务回放与人物关系图更新程序")
    parser.add_argument(
        "command",
        choices=["validate-contract", "bootstrap", "capture", "plan", "publish", "status"],
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--reference-month", type=int)
    parser.add_argument("--graph-credentials", type=Path)
    parser.add_argument("--max-transactions", type=int, default=100)
    parser.add_argument("--max-rows", type=int, default=10_000)
    args = parser.parse_args()
    if args.command != "validate-contract" and args.state is None:
        parser.error("该命令需要独立 --state 目录")
    if args.command in ("bootstrap", "capture") and args.input is None:
        parser.error("该命令需要 --input")
    if args.command in ("bootstrap", "plan", "publish") and args.reference_month is None:
        parser.error("该命令需要明确 --reference-month")
    if args.command == "publish" and args.graph_credentials is None:
        parser.error("publish需要显式 --graph-credentials")
    try:
        result = _execute(args)
    except UpdateError as error:
        print(
            json.dumps({"ok": False, "code": error.code, "message": str(error)}, ensure_ascii=False)
        )
        return 1
    except ValidationError:
        print(
            json.dumps(
                {"ok": False, "code": "INVALID_INPUT", "message": "配置或输入不符合版本化协议"},
                ensure_ascii=False,
            )
        )
        return 1
    except (OSError, ValueError, sqlite3.Error) as error:
        print(
            json.dumps({"ok": False, "code": "UPDATE_IO_ERROR", "error_type": type(error).__name__})
        )
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


def _execute(args: argparse.Namespace) -> dict:
    contract = SourceContract.model_validate_json(args.contract.read_text())
    adapter = NumericProjectionAdapter(contract)
    if args.command == "validate-contract":
        return {"contract_version": contract.version, "contract_digest": contract.fingerprint}
    if min(args.max_rows, args.max_transactions) < 1:
        raise UpdateError("INVALID_BUDGET", "行数和微批事务预算必须为正数")
    if args.reference_month is not None:
        TypeAdapter(Month).validate_python(args.reference_month)
    snapshot = read_snapshot(args.input) if args.command == "bootstrap" else None
    if snapshot is not None:
        # 验证失败不创建状态目录，便于修正输入后重试。
        rows = contract.snapshot(snapshot.tables)
        if sum(len(records) for records in rows.values()) > args.max_rows:
            raise UpdateError("ROW_LIMIT", "全量输入达到本次行数预算")
        adapter.build(rows, args.reference_month)
    store = UpdateStore(args.state, contract, create=args.command == "bootstrap")
    program = UpdateProgram(store, adapter, max_rows=args.max_rows)
    if snapshot is not None:
        program.bootstrap(snapshot, args.reference_month)
        return {"status": "baseline_imported", "input_kind": "offline-replay"}
    if args.command == "capture":
        return {"input_kind": "offline-replay", **program.capture(ReplaySource(args.input))}
    if args.command == "status":
        active = load_active(store.directory, contract)
        return {"capture": store.status(), "active_revision": active[0].revision if active else 0}
    target = NebulaTarget(args.graph_credentials) if args.command == "publish" else None
    manifest = program.process(args.reference_month, target, max_transactions=args.max_transactions)
    return {"result": manifest.model_dump(mode="json") if manifest else "up_to_date"}


if __name__ == "__main__":
    raise SystemExit(main())
