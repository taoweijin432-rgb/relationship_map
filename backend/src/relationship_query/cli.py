import argparse
import json
import os
from pathlib import Path

from relationship_query.domain.validation import input_error_report, validate_payload
from relationship_query.infrastructure.fixtures import make_dataset
from relationship_query.infrastructure.sqlite import load_dataset, open_engine
from relationship_query.settings import database_path


def main() -> int:
    parser = argparse.ArgumentParser(description="只管理本地虚构数据，不连接生产数据库")
    parser.add_argument("command", choices=["init", "reset", "export-openapi", "validate-dataset"])
    parser.add_argument("--size", type=int, default=60)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    if args.command == "validate-dataset":
        if args.input is None:
            parser.error("validate-dataset 需要 --input")
        return _validate_file(args.input)
    if args.input is not None:
        parser.error("--input 只用于 validate-dataset")
    if args.command == "export-openapi":
        from relationship_query.app import create_app

        print(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2))
        return 0
    if os.environ.get("RELATIONSHIP_MYSQL_URL"):
        parser.error("init/reset 仅管理 SQLite；MySQL 请使用独立实验导入入口，不支持原位重置")
    if (
        os.environ.get("RELATIONSHIP_SOURCE_API_MANIFEST")
        or os.environ.get("RELATIONSHIP_SOURCE_API_MYSQL_URL")
        or os.environ.get("RELATIONSHIP_SOURCE_RELEASE_STORE")
    ):
        parser.error("原表集成模式不支持 init/reset；请停服后重新发布独立快照")
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = open_engine(path)
    try:
        changed = load_dataset(engine, make_dataset(args.size), reset=args.command == "reset")
    finally:
        engine.dispose()
    print(f"{'已初始化虚构数据' if changed else '保留已有数据'}：{path}")
    return 0


def _validate_file(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        report = input_error_report("INPUT_READ_ERROR", "无法读取 UTF-8 逻辑样例文件")
    except json.JSONDecodeError as exc:
        report = input_error_report(
            "INVALID_JSON", f"JSON 格式错误：行 {exc.lineno}，列 {exc.colno}"
        )
    else:
        _, report = validate_payload(payload)
    print(report.model_dump_json(indent=2))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
