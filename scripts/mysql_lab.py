"""在授权的本地 MySQL 中新建独立模拟实验库；已有库绝不覆盖。"""

import argparse
import hashlib
import json
import os
import secrets
import shlex
from datetime import datetime
from pathlib import Path
from time import perf_counter

from relationship_query.infrastructure.mysql import LAB_DATABASE, open_mysql_engine
from relationship_query.infrastructure.mysql_dataset import import_snapshot
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.input.is_file() or args.output.exists():
        parser.error("输入快照必须存在，输出目录必须是新目录")
    admin = make_url(
        os.environ.get(
            "RELATIONSHIP_MYSQL_ADMIN_URL", "mysql+pymysql://root@127.0.0.1:3306"
        )
    )
    if (
        admin.drivername != "mysql+pymysql"
        or admin.host not in {"localhost", "127.0.0.1"}
        or admin.database
        or admin.query
    ):
        parser.error("管理员连接仅允许本机 mysql+pymysql，不指定数据库或附加参数")
    database = (
        "relationship_lab_" + datetime.now().strftime("%Y%m%d_") + secrets.token_hex(4)
    )
    assert LAB_DATABASE.fullmatch(database)
    args.output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    before = hashlib.sha256(args.input.read_bytes()).hexdigest()
    control = create_engine(
        admin, connect_args={"connect_timeout": 3}, hide_parameters=True
    )
    try:
        with control.connect() as connection:
            version = connection.scalar(text("SELECT VERSION()"))
            connection.execute(
                text(
                    f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin"
                )
            )
    finally:
        control.dispose()
    url = admin.set(database=database, query={"charset": "utf8mb4"}).render_as_string(
        hide_password=False
    )
    config = args.output / ".env"
    config.touch(mode=0o600, exist_ok=False)
    config.write_text("export RELATIONSHIP_MYSQL_URL=" + shlex.quote(url) + "\n")
    engine = open_mysql_engine(url, writable=True)
    try:
        result = import_snapshot(args.input, engine)
    finally:
        engine.dispose()
    after = hashlib.sha256(args.input.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("源快照在导入期间变化，实验无效，请停服务后重新导入新库")
    report = {
        "database": database,
        "mysql_version": version,
        "snapshot_sha256": before,
        "snapshot_unchanged": True,
        "import_ms": round((perf_counter() - started) * 1000, 2),
        **result,
    }
    (args.output / "import.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"连接配置已保存到 {config}（权限 600，不输出连接字符串）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
