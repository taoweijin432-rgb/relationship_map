"""使用 backend/.venv 验收固定的本机 NebulaGraph 环境，不接受任意查询。"""

import argparse
import json
from pathlib import Path

from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    bootstrap,
    check,
    smoke,
    verify,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["bootstrap", "check", "smoke", "verify"])
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error("验收报告不得覆盖已有文件")
    if args.command == "verify":
        if not args.input:
            parser.error("verify 需要 --input 验收记录")
        result = verify(args.credentials, json.loads(args.input.read_text()))
    elif args.command == "smoke":
        if not args.output:
            parser.error("smoke 需要 --output 保留可供重启核对的记录")
        result = smoke(args.credentials)
    else:
        result = (
            bootstrap(args.credentials)
            if args.command == "bootstrap"
            else check(args.credentials)
        )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as report:
            report.write(payload)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
