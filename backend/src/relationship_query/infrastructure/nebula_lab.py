"""本地图数据库环境验收；不作为业务查询仓储或生产图投影。"""

import json
import os
import re
import secrets
import stat
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Literal

from nebula3.Config import Config  # type: ignore[import-untyped]
from nebula3.Exception import AuthFailedException  # type: ignore[import-untyped]
from nebula3.gclient.net import ConnectionPool  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

from relationship_query.settings import DEFAULT_DATABASE

DEFAULT_CREDENTIALS = DEFAULT_DATABASE.parent / "nebula-lab" / "credentials.json"
SPACE = re.compile(r"relationship_lab_[a-z0-9_]{1,40}\Z")


class LabCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: Literal[19669] = 19669
    username: Literal["root"] = "root"
    password: SecretStr
    bootstrapped: bool = False

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[0-9a-f]{24}", value.get_secret_value()):
            raise ValueError("实验凭据必须为本工具生成的 24 位十六进制值")
        return value


class LabQueryError(RuntimeError):
    def __init__(self, code: int) -> None:
        self.code = code
        # 服务端解析错误可能包含原语句；不将密码变更语句或原错误文本输出。
        super().__init__(f"NebulaGraph 操作失败，错误码 {code}")


class LabAuthenticationError(RuntimeError):
    pass


def save_credentials(path: Path, config: LabCredentials) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {**config.model_dump(mode="json"), "password": config.password.get_secret_value()}
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as temporary:
        name = Path(temporary.name)
        json.dump(payload, temporary)
    try:
        os.replace(name, path)
    finally:
        name.unlink(missing_ok=True)


def load_credentials(path: Path, *, create: bool = False) -> LabCredentials:
    if not path.exists():
        if not create:
            raise ValueError("实验凭据不存在，请先运行 bootstrap")
        config = LabCredentials(password=SecretStr(secrets.token_hex(12)))
        save_credentials(path, config)
        return config
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("实验凭据权限应为 600，请检查本机文件权限")
    return LabCredentials.model_validate_json(path.read_text())


@contextmanager
def connect(config: LabCredentials, *, bootstrap: bool = False) -> Iterator[Any]:
    pool = ConnectionPool()
    options = Config()
    # 仅环境初始化与 CRUD 验收，给冷启动 Schema／分区操作留出有限等待；非业务 SLA。
    options.timeout = 15000
    options.max_connection_pool_size = 2
    session = None
    try:
        deadline = monotonic() + 60
        while True:
            try:
                if not pool.init([(config.host, config.port)], options):
                    raise RuntimeError("NebulaGraph 连接池未就绪")
                break
            except RuntimeError as exc:
                if (
                    not bootstrap
                    or "services status exception" not in str(exc)
                    or monotonic() >= deadline
                ):
                    raise
                pool.close()
                pool = ConnectionPool()
                sleep(1)
        try:
            session = pool.get_session(config.username, config.password.get_secret_value())
        except AuthFailedException:
            if not bootstrap or config.bootstrapped:
                raise LabAuthenticationError("实验凭据认证失败，未尝试覆盖或重置密码") from None
            session = pool.get_session("root", "nebula")
            query(session, f"ALTER USER root WITH PASSWORD '{config.password.get_secret_value()}'")
        yield session
    finally:
        if session is not None:
            session.release()
        pool.close()


def query(session: Any, statement: str, *, wait: bool = False) -> list[dict[str, Any]]:
    deadline = monotonic() + 60
    while True:
        result = session.execute(statement)
        if result.is_succeeded():
            return list(result.as_primitive())
        code = result.error_code()
        # DDL、分区分配和 leader 异步可见，只重试明确的短暂状态，不吞解析／权限错误。
        message = result.error_msg()
        pending_space = code == -1005 and message.startswith("SpaceNotFound:")
        pending_schema = code == -1009 and message.startswith("SemanticError: No schema found for ")
        pending_storage_schema = code == -1005 and message in {
            "Storage Error: Tag not found.",
            "Storage Error: Edge not found.",
        }
        if (
            not wait
            or not (
                code in {-4, -5, -6, -7, -16}
                or pending_space
                or pending_schema
                or pending_storage_schema
            )
            or monotonic() >= deadline
        ):
            raise LabQueryError(code)
        sleep(1)


def bootstrap(path: Path) -> dict[str, Any]:
    config = load_credentials(path, create=True)
    with connect(config, bootstrap=True) as session:
        ready = config.model_copy(update={"bootstrapped": True})
        save_credentials(path, ready)
        hosts = query(session, "SHOW HOSTS")
        if not any(row.get("Host") == "storaged" and row.get("Port") == 9779 for row in hosts):
            query(session, 'ADD HOSTS "storaged":9779')
    return check(path, wait=True)


def check(path: Path, *, wait: bool = False) -> dict[str, Any]:
    config = load_credentials(path)
    deadline = monotonic() + 60
    with _after_auth_propagation(config, wait=wait) as session:
        while True:
            hosts = query(session, "SHOW HOSTS")
            online = any(
                row.get("Host") == "storaged" and row.get("Status") == "ONLINE" for row in hosts
            )
            if online or not wait or monotonic() >= deadline:
                break
            sleep(1)
        if not online:
            raise RuntimeError("Storage 主机尚未 ONLINE，环境未就绪")
        return {
            "endpoint": f"{config.host}:{config.port}",
            "storage_hosts": hosts,
            "graph_hosts": query(session, "SHOW HOSTS GRAPH"),
            "authentication": True,
        }


@contextmanager
def _after_auth_propagation(config: LabCredentials, *, wait: bool) -> Iterator[Any]:
    deadline = monotonic() + 60
    while True:
        with ExitStack() as stack:
            try:
                session = stack.enter_context(connect(config))
            except LabAuthenticationError:
                if not wait or monotonic() >= deadline:
                    raise
                # 仅等待新密码向 Graph 的认证缓存传播，每次回收失败的 SDK 池。
                sleep(1)
                continue
            yield session
            return


def require_space(space: str) -> str:
    if not SPACE.fullmatch(space):
        raise ValueError("仅操作 relationship_lab_ 前缀实验图空间")
    return space


def _create_smoke_schema(session: Any, space: str) -> None:
    query(
        session,
        f"CREATE SPACE `{require_space(space)}` "
        "(partition_num=1, replica_factor=1, vid_type=FIXED_STRING(128))",
    )
    query(session, f"USE `{space}`", wait=True)
    query(session, "CREATE TAG person(name string)", wait=True)
    query(session, "CREATE TAG organization(name string)", wait=True)
    query(
        session,
        "CREATE EDGE employment(fact_id string, role_id string, start_month int, "
        "end_month int, is_current bool, active bool, "
        "source_system string, source_record_id string)",
        wait=True,
    )


def _insert_smoke(session: Any) -> None:
    query(
        session,
        'INSERT VERTEX person(name) VALUES "p:lab:01":("虚构人物甲"), "p:lab:02":("虚构人物乙")',
        wait=True,
    )
    query(session, 'INSERT VERTEX organization(name) VALUES "org:lab":("虚构实验公司")', wait=True)
    query(
        session,
        """INSERT EDGE employment(fact_id,role_id,start_month,end_month,
        is_current,active,source_system,source_record_id) VALUES
        "p:lab:01"->"org:lab"@1:("fact:lab:01","role:engineer",202001,202212,false,true,"expert","fictional:expert:01"),
        "p:lab:01"->"org:lab"@2:("fact:lab:02","role:director",NULL,NULL,false,true,"resume","fictional:resume:02"),
        "p:lab:02"->"org:lab"@3:("fact:lab:03","role:engineer",202101,NULL,true,true,"resume","fictional:resume:03")""",
        wait=True,
    )


def _read_smoke(session: Any) -> dict[str, Any]:
    vertices = query(
        session,
        'FETCH PROP ON person "p:lab:01", "p:lab:02" '
        "YIELD id(vertex) AS person_id, properties(vertex).name AS name",
    )
    edges = query(
        session,
        'GO FROM "p:lab:01", "p:lab:02" OVER employment '
        "YIELD src(edge) AS person_id, dst(edge) AS entity_id, "
        "rank(edge) AS fact_rank, properties(edge) AS fact",
    )
    vertices.sort(key=lambda row: row["person_id"])
    edges.sort(key=lambda row: row["fact_rank"])
    if [row["name"] for row in vertices] != ["虚构人物甲", "虚构人物乙"]:
        raise RuntimeError("人物／中文读取不符合预期")
    if [row["fact"]["fact_id"] for row in edges] != ["fact:lab:01", "fact:lab:02", "fact:lab:03"]:
        raise RuntimeError("经历数量或重复任职边被覆盖")
    if edges[1]["fact"]["start_month"] is not None or not edges[2]["fact"]["is_current"]:
        raise RuntimeError("空日期或当前任职属性读取不符合预期")
    if edges[0]["fact"]["source_record_id"] != "fictional:expert:01":
        raise RuntimeError("来源定位读取不符合预期")
    return {"people": vertices, "employment_edges": edges}


def smoke(path: Path) -> dict[str, Any]:
    config = load_credentials(path)
    space = "relationship_lab_smoke_" + secrets.token_hex(6)
    with connect(config) as session:
        _create_smoke_schema(session, space)
        _insert_smoke(session)
        before = _read_smoke(session)
        plan = query(
            session, 'PROFILE GO FROM "p:lab:01" OVER employment YIELD dst(edge) AS entity_id'
        )
        query(session, 'DELETE EDGE employment "p:lab:01"->"org:lab"@2')
        remaining = query(
            session, 'GO FROM "p:lab:01" OVER employment YIELD rank(edge) AS fact_rank'
        )
        if remaining != [{"fact_rank": 1}]:
            raise RuntimeError("按经历边标识删除不符合预期")
        _insert_smoke(session)
        if _read_smoke(session) != before:
            raise RuntimeError("重放写入后的事实与初始值不一致")
    return {
        "data_mode": "mock",
        "environment_only": True,
        "space": space,
        "checks": [
            "utf8_read_write",
            "parallel_fact_edges",
            "null_and_current",
            "source_reference",
            "profile",
            "edge_delete",
            "idempotent_write",
        ],
        "expected": before,
        "profile_rows": plan,
    }


def verify(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    space = require_space(report["space"])
    with connect(load_credentials(path)) as session:
        query(session, f"USE `{space}`", wait=True)
        current = _read_smoke(session)
    if current != report["expected"]:
        raise RuntimeError("图空间数据与验收记录不一致")
    return {"space": space, "snapshot_matches": True, "read_only_check": True}
