"""配置服务器人物在线读取与夜间自动采集，凭据只写入私有EnvironmentFile。"""

import argparse
import getpass
import json
import os
import re
import runpy
import shlex
import shutil
import tempfile
from pathlib import Path

from relationship_query.infrastructure.live_people import MySQLPeople, open_people_engine
from relationship_query.update.nightly import NightlyConfig, NightlyPublisher, atomic_file
from relationship_query.update.source_config import MySQLSourceConfig

ROOT = Path(__file__).resolve().parents[1]


def read_environment(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("MySQL环境文件含非法变量名")
        parsed = shlex.split(value, comments=True)
        if len(parsed) != 1:
            raise ValueError("MySQL环境变量值须为单行字符串")
        result[key] = parsed[0]
    return result


def environment_bytes(values: dict[str, str]) -> bytes:
    if any("\n" in value or "\r" in value or "\x00" in value for value in values.values()):
        raise ValueError("MySQL环境变量值须为单行字符串")
    lines = []
    for key, value in sorted(values.items()):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}="{escaped}"\n')
    return "".join(lines).encode()


def password_config(
    sources: MySQLSourceConfig, values: dict[str, str], prompt_passwords: bool
) -> MySQLSourceConfig:
    data = sources.model_dump(mode="json")
    roles = {sources.entity_source: "ENTITY", sources.person_source: "PERSON"}
    for name, role in roles.items():
        endpoint = data["connections"][name]
        variable = endpoint.get("password_env") or f"RELATIONSHIP_{role}_MYSQL_PASSWORD"
        endpoint["password_env"] = variable
        if prompt_passwords or not values.get(variable):
            values[variable] = getpass.getpass(
                f"{endpoint['host']} {endpoint['user']} MySQL password: "
            )
        if not values[variable]:
            raise ValueError("来源密码为空")
    return MySQLSourceConfig.model_validate(data)


def verify_sources(sources: MySQLSourceConfig, nightly: NightlyConfig, insecure_tls: bool) -> None:
    _, release = NightlyPublisher(nightly)._environment()
    manifest = json.loads((release / "manifest.json").read_text())
    capture = runpy.run_path(str(ROOT / "scripts/capture_real_graph_sources.py"))
    with capture["source_session"](sources.endpoint("entities"), insecure_tls) as connection:
        metadata = capture["source_metadata"](
            connection, sources.endpoint("entities"), insecure_tls
        )
        old = manifest["sources"][0]
        if any(metadata[key] != old[key] for key in ("host", "port", "database")) or (
            metadata["server"]["server_uuid"] != old["server"]["server_uuid"]
        ):
            raise ValueError("实体来源与当前发布不一致，请先完成来源迁移基线")
    engine = open_people_engine(sources, insecure_tls)
    try:
        MySQLPeople(engine).check(sources, manifest["sources"][1])
    finally:
        engine.dispose()


def write_configuration(project: Path, outputs: dict[Path, bytes]) -> Path:
    backup_root = project / "data/deployment-backups"
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix="before-live-mysql-", dir=backup_root))
    previous = {path: path.read_bytes() if path.exists() else None for path in outputs}
    for path, content in previous.items():
        if content is not None:
            target = backup / path.name
            shutil.copy2(path, target)
            target.chmod(0o600)
    try:
        for path, content in outputs.items():
            atomic_file(path, content)
    except OSError:
        for path, content in previous.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_file(path, content)
        raise
    return backup


def configure(directory: Path, *, insecure_tls: bool, prompt_passwords: bool) -> None:
    source_file, nightly_file, secret_file = (
        directory / name for name in ("mysql-sources.json", "nightly.json", "mysql.env")
    )
    values = read_environment(secret_file)
    sources = password_config(MySQLSourceConfig.read(source_file), values, prompt_passwords)
    nightly = NightlyConfig.model_validate_json(nightly_file.read_text())
    os.environ.update(values)
    verify_sources(sources, nightly, insecure_tls)
    settings = nightly.model_copy(
        update={
            "source_config_file": source_file.resolve(),
            "insecure_source_tls": insecure_tls,
        }
    )
    values["RELATIONSHIP_MYSQL_SOURCE_CONFIG"] = str(source_file.resolve())
    values["RELATIONSHIP_MYSQL_INSECURE_TLS"] = "1" if insecure_tls else "0"
    backup = write_configuration(
        nightly.project_directory,
        {
            source_file: sources.model_dump_json(indent=2).encode(),
            nightly_file: settings.model_dump_json(indent=2).encode(),
            secret_file: environment_bytes(values),
        },
    )
    print(
        json.dumps(
            {
                "configured": True,
                "person_display": "mysql-live",
                "automatic_nightly_input": True,
                "certificate_verified": not insecure_tls,
                "backup": str(backup),
                "environment_file": str(secret_file),
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-directory", type=Path, default=Path("/etc/relationship-map"))
    parser.add_argument("--insecure-tls", action="store_true")
    parser.add_argument("--prompt-passwords", action="store_true")
    args = parser.parse_args()
    configure(
        args.config_directory.resolve(),
        insecure_tls=args.insecure_tls,
        prompt_passwords=args.prompt_passwords,
    )


if __name__ == "__main__":
    main()
