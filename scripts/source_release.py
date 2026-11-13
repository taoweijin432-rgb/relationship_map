"""本机原表批次的停服激活、回退和状态查询，不自动停止任何服务。"""

import argparse
from pathlib import Path

from relationship_query.infrastructure.source_releases import activate, read_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["activate", "rollback", "status"])
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--release", type=Path)
    args = parser.parse_args()
    if (args.command == "activate") != (args.release is not None):
        parser.error("activate 必须指定 --release，其他命令不得指定")
    if args.command == "status":
        state = read_state(args.store)
    else:
        state = activate(args.store, args.release, rollback=args.command == "rollback")
    print(state.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
