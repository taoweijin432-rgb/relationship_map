"""独立容器模拟远程 TLS MySQL，复制虚构冻结源并执行专项，结束回收本次容器。"""

import argparse
import hashlib
import json
import os
import secrets
import shlex
import shutil
import ssl
import subprocess
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep

from projection_source_lab import raw_statements, save
from relationship_query.infrastructure.mysql import RemoteMySQL
from relationship_query.infrastructure.source_read_model import snapshot, source_digest
from relationship_query.infrastructure.source_releases import read_bundle
from relationship_query.infrastructure.sql_release_guard import install
from relationship_query.infrastructure.uuid_source import (
    NAMES,
    UUIDManifest,
    mock_schema,
    reflect,
)
from relationship_query.infrastructure.uuid_verification import verify_bundle_graph
from sqlalchemy import DateTime, create_engine, insert
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import OperationalError

ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "mysql:8.4@sha256:a81d043930e51745522bd5c430961cf8286f0a23f0a9a2a6e0108f7ea71b0902"
)


def command(*args: str) -> str:
    return subprocess.run(
        args, check=True, text=True, capture_output=True
    ).stdout.strip()


def certificates(output: Path) -> None:
    tls = output / "tls"
    tls.mkdir(mode=0o755)
    command(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-subj",
        "/CN=Relationship Demo Test CA",
        "-keyout",
        str(tls / "ca-key.pem"),
        "-out",
        str(output / "mysql-ca.pem"),
    )
    command(
        "openssl",
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-subj",
        "/CN=localhost",
        "-keyout",
        str(tls / "server-key.pem"),
        "-out",
        str(tls / "server.csr"),
    )
    extensions = tls / "extensions.cnf"
    extensions.write_text(
        "subjectAltName=DNS:localhost\nbasicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
    )
    command(
        "openssl",
        "x509",
        "-req",
        "-in",
        str(tls / "server.csr"),
        "-CA",
        str(output / "mysql-ca.pem"),
        "-CAkey",
        str(tls / "ca-key.pem"),
        "-CAcreateserial",
        "-days",
        "2",
        "-extfile",
        str(extensions),
        "-out",
        str(tls / "server-cert.pem"),
    )
    shutil.copyfile(output / "mysql-ca.pem", tls / "ca.pem")
    command(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-subj",
        "/CN=Untrusted Demo CA",
        "-keyout",
        str(tls / "untrusted-key.pem"),
        "-out",
        str(tls / "untrusted-ca.pem"),
    )
    # 仅测试服务密钥需供容器 mysql UID 读取，整个实验目录保持 700。
    (tls / "server-key.pem").chmod(0o644)
    (tls / "ca-key.pem").chmod(0o600)


def start_container(output: Path, name: str) -> URL:
    password = secrets.token_hex(24)
    env = output / "container.env"
    env.touch(mode=0o600)
    env.write_text(f"MYSQL_ROOT_PASSWORD={password}\nMYSQL_ROOT_HOST=%\n")
    command(
        "docker",
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--cidfile",
        str(output / "container-id"),
        "--publish",
        "127.0.0.1::3306",
        "--env-file",
        str(env),
        "--mount",
        f"type=bind,src={output / 'tls'},dst=/etc/mysql/lab-tls,readonly",
        IMAGE,
        "--require-secure-transport=ON",
        "--ssl-ca=/etc/mysql/lab-tls/ca.pem",
        "--ssl-cert=/etc/mysql/lab-tls/server-cert.pem",
        "--ssl-key=/etc/mysql/lab-tls/server-key.pem",
    )
    port = int(command("docker", "port", name, "3306/tcp").rsplit(":", 1)[1])
    return URL.create(
        "mysql+pymysql", username="root", password=password, host="localhost", port=port
    )


def admin_engine(url: URL, output: Path) -> Engine:
    context = ssl.create_default_context(cafile=str(output / "mysql-ca.pem"))
    engine = create_engine(
        url, connect_args={"ssl": context, "connect_timeout": 2}, hide_parameters=True
    )
    deadline = monotonic() + 90
    while True:
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            return engine
        except OperationalError:
            if monotonic() >= deadline:
                engine.dispose()
                raise
            sleep(1)


def populate(engine: Engine, rows: dict) -> dict:
    with engine.connect() as connection:
        for ddl in raw_statements():
            connection.exec_driver_sql(ddl)
    mock_schema().create_all(engine, checkfirst=False)
    schema = reflect(engine)
    with engine.begin() as connection:
        for table in schema.sorted_tables:
            records = []
            for row in rows[table.name]:
                record = dict(row)
                for column in table.columns:
                    value = record.get(column.name)
                    if isinstance(value, str) and isinstance(column.type, DateTime):
                        record[column.name] = datetime.fromisoformat(value)
                records.append(record)
            if records:
                connection.execute(insert(table), records)
    with engine.connect() as connection:
        return snapshot(connection, schema, NAMES)


def prepare(source: Path, output: Path, admin: URL) -> dict:
    prior = read_bundle(source)
    if (
        not isinstance(prior.manifest, UUIDManifest)
        or prior.manifest.format_version != 4
    ):
        raise ValueError("仅复制本机已冻结 format_version=4 的虚构来源")
    root = admin_engine(admin, output)
    database = "demo_remote_" + secrets.token_hex(6)
    try:
        with root.connect() as connection:
            version = connection.exec_driver_sql("SELECT VERSION()").scalar_one()
            connection.exec_driver_sql(
                f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4"
            )
    finally:
        root.dispose()
    writer_url = admin.set(database=database)
    writer = admin_engine(writer_url, output)
    password = secrets.token_hex(24)
    reader = writer_url.set(username="demo_reader", password=password)
    try:
        frozen = populate(
            writer, json.loads((source / "source-snapshot.json").read_text())
        )
        if source_digest(frozen) != prior.manifest.source_digest:
            raise ValueError("模拟源复制后的完整摘要不一致")
        endpoint = RemoteMySQL(
            host="localhost",
            port=admin.port,
            ca_sha256=hashlib.sha256(
                (output / "mysql-ca.pem").read_bytes()
            ).hexdigest(),
        )
        manifest = UUIDManifest.model_validate(
            {
                **prior.manifest.model_dump(),
                "format_version": 5,
                "source_database": database,
                "source_endpoint": endpoint.model_dump(),
            }
        )
        install(writer, manifest)
        with writer.connect() as connection:
            connection.exec_driver_sql(
                "CREATE USER 'demo_reader'@%s IDENTIFIED BY %s REQUIRE SSL",
                ("%", password),
            )
            connection.exec_driver_sql(
                f"GRANT SELECT ON `{database}`.* TO 'demo_reader'@%s", ("%",)
            )
    finally:
        writer.dispose()
    for name in ("reader-credentials.json", "graph-nodes.json", "graph-edges.json"):
        shutil.copyfile(source / name, output / name)
    (output / "reader-credentials.json").chmod(0o600)
    save(output / "source-snapshot.json", frozen)
    save(output / "manifest.json", manifest.model_dump(mode="json"))
    private = output / "admin.env"
    private.touch(mode=0o600)
    private.write_text(
        "export RELATIONSHIP_REMOTE_MYSQL_ADMIN_URL="
        + shlex.quote(writer_url.render_as_string(hide_password=False))
        + "\n"
    )
    config = output / "api.env"
    config.touch(mode=0o600)
    config.write_text(
        "export RELATIONSHIP_SOURCE_API_MANIFEST="
        + shlex.quote(str(output / "manifest.json"))
        + "\nexport RELATIONSHIP_SOURCE_API_MYSQL_URL="
        + shlex.quote(reader.render_as_string(hide_password=False))
        + "\n"
    )
    verify_bundle_graph(output)
    return {
        "data_mode": "mock",
        "mysql_version": version,
        "database": database,
        "source_digest": manifest.source_digest,
        "graph_reused": manifest.space,
        "geographic_remote": False,
        "tls_host": "localhost",
        "tls_port": admin.port,
    }


def run(source: Path, output: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    certificates(output)
    name = "relationship-remote-mysql-" + secrets.token_hex(6)
    verified = False
    try:
        admin = start_container(output, name)
        report = prepare(source, output, admin)
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("RELATIONSHIP_")
        }
        environment.update(
            RELATIONSHIP_REMOTE_MYSQL_TEST_DIR=str(output),
            RELATIONSHIP_UUID_TEST_DIR=str(output),
        )
        result = subprocess.run(
            [
                str(ROOT / "backend/.venv/bin/python"),
                "-m",
                "pytest",
                "backend/tests/test_uuid_graph.py",
                "backend/tests/test_remote_mysql.py",
                "-q",
                f"--junitxml={output / 'tests.xml'}",
            ],
            cwd=ROOT,
            check=False,
            env=environment,
            text=True,
            capture_output=True,
        )
        (output / "tests.log").write_text(result.stdout + result.stderr)
        report["tests_exit_code"] = result.returncode
        if result.returncode:
            raise RuntimeError(f"远程模拟专项失败，检查 {output / 'tests.log'}")
        verified = True
    finally:
        manifest_path = output / "manifest.json"
        if not verified and manifest_path.exists():
            manifest_path.rename(output / "failed-manifest.json")
        # 名称仅由本次随机生成，结束回收本容器及其匿名测试卷。
        container_id = output / "container-id"
        if container_id.exists():
            identity = container_id.read_text().strip()
            if command("docker", "ps", "--all", "--quiet", "--filter", f"id={identity}"):
                command("docker", "stop", "--time", "10", identity)
    report["container_stopped"] = True
    save(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(run(args.source_bundle, args.output), ensure_ascii=False, indent=2)
    )
