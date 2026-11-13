"""从独立模拟 SQLite 快照构建新 NebulaGraph 投影，拒绝覆盖。"""

import argparse
from pathlib import Path

from relationship_query.infrastructure.graph_projection import project_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = project_snapshot(args.input, args.output)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
