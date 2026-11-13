"""只使用规模报告中已登记的虚构库，启动并回收本机浏览器观察服务。"""

import argparse
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import quote

from relationship_query.benchmark.report import file_digest
from relationship_query.settings import DEFAULT_DATABASE

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="R01 规模浏览器观察，需先停止普通开发服务"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    database, output = args.database.resolve(), args.output.resolve()
    if database == DEFAULT_DATABASE.resolve() or not database.is_file():
        parser.error("必须使用已生成的独立规模库")
    if output.exists():
        parser.error("拒绝覆盖已有浏览器报告")
    manifest_path = database.parent / "report.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        registered = any(
            item.get("database") == str(database)
            and item["generation"]["profile"] == "scale-v1"
            for item in manifest["datasets"]
        )
        if not registered:
            raise ValueError("数据文件不在规模报告中")
        with sqlite3.connect(
            f"file:{quote(str(database))}?mode=ro", uri=True
        ) as connection:
            version = connection.execute("SELECT version FROM demo_dataset").fetchone()[
                0
            ]
        if not version.startswith("scale-v1-"):
            raise ValueError("不是规模虚构数据版本")
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.error(f"规模库检查失败：{exc}")
    output.parent.mkdir(parents=True, exist_ok=True)
    before_db, before_demo = file_digest(database), file_digest(DEFAULT_DATABASE)
    environment = {
        **os.environ,
        "CI": "1",
        "RELATIONSHIP_DATABASE": str(database),
        "RELATIONSHIP_SCALE_BROWSER": "1",
        "RELATIONSHIP_SCALE_OUTPUT": str(output),
    }
    result = subprocess.run(
        [
            "node",
            "node_modules/@playwright/test/cli.js",
            "test",
            "tests/scale-performance.spec.ts",
        ],
        cwd=ROOT / "frontend",
        env=environment,
        check=False,
    )
    if output.is_file():
        report = json.loads(output.read_text())
        report.update(
            {
                "data_version": version,
                "database_unchanged": before_db == file_digest(database),
                "default_database_unchanged": before_demo
                == file_digest(DEFAULT_DATABASE),
            }
        )
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not report["database_unchanged"] or not report["default_database_unchanged"]:
            return 1
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
