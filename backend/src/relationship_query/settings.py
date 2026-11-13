import json
import os
from pathlib import Path

DEFAULT_DATABASE = Path(__file__).resolve().parents[3] / "data" / "mock-v1.sqlite"
DEFAULT_FRONTEND_SOURCE = DEFAULT_DATABASE.parent / "frontend-source.json"


def database_path() -> Path:
    return Path(os.environ.get("RELATIONSHIP_DATABASE", str(DEFAULT_DATABASE))).resolve()


def default_numeric_store() -> Path | None:
    if not DEFAULT_FRONTEND_SOURCE.exists():
        return None
    config = json.loads(DEFAULT_FRONTEND_SOURCE.read_text())
    if set(config) != {"format", "store"} or config["format"] != "numeric-query-source-v1":
        raise ValueError("前端默认数据源配置格式不正确")
    return (DEFAULT_FRONTEND_SOURCE.parent / config["store"]).resolve()
