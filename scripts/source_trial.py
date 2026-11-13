"""只消费本地采样文件，生成独立模拟数据源与查询快照；不连接 Supabase。"""

import argparse
import json
from pathlib import Path

from relationship_query.infrastructure.source_trial import (
    prepare_trial,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare_trial(args.input, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(
            json.dumps({"status": "invalid", "message": str(exc)}, ensure_ascii=False)
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
