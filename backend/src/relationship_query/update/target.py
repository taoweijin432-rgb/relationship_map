"""图目标接口与Nebula实现。只有新空间完整回读后才返回验证收据。"""

from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Protocol, cast
from uuid import uuid4

from nebula3.Config import Config  # type: ignore[import-untyped]
from nebula3.Exception import AuthFailedException  # type: ignore[import-untyped]
from nebula3.gclient.net import ConnectionPool  # type: ignore[import-untyped]

from relationship_query.infrastructure.graph_model import ReaderCredentials
from relationship_query.infrastructure.graph_projection import ProjectionWriter, _reader_account
from relationship_query.infrastructure.nebula_lab import (
    LabQueryError,
    connect,
    load_credentials,
    query,
)
from relationship_query.infrastructure.uuid_projection import (
    calculate_relations,
    estimate,
    graph_digest,
    insert_edges,
    insert_nodes,
    read_all,
    schema_statements,
)
from relationship_query.update.artifacts import write_json
from relationship_query.update.models import GraphReceipt, Projection, UpdateError


@dataclass(frozen=True)
class BuildContext:
    directory: Path
    version: str
    source_digest: str
    reference_month: int


class GraphTarget(Protocol):
    def build_and_verify(self, projection: Projection, context: BuildContext) -> GraphReceipt: ...


def verify_reader(reader: ReaderCredentials, space: str, meta: dict[str, Any]) -> None:
    """账号与角色异步传播，确认实际只读身份可见完成标记后才交付收据。"""
    deadline = monotonic() + 60
    while True:
        pool, session = ConnectionPool(), None
        config = Config()
        config.timeout, config.max_connection_pool_size = 15000, 1
        try:
            if not pool.init([(reader.host, reader.port)], config):
                raise UpdateError("GRAPH_READER_UNAVAILABLE", "图只读连接池未就绪")
            session = pool.get_session(reader.username, reader.password.get_secret_value())
            rows = query(
                session,
                f'USE `{space}`; FETCH PROP ON projection_meta "meta:projection" '
                "YIELD properties(vertex) AS meta",
            )
            if rows != [{"meta": meta}]:
                raise UpdateError("GRAPH_INTEGRITY", "图只读账号完成标记核对不符")
            return
        except (AuthFailedException, LabQueryError):
            # 固定语句已通过管理员核对，等待新账号及授权的有界传播。
            if monotonic() >= deadline:
                raise UpdateError(
                    "GRAPH_READER_UNAVAILABLE", "图只读账号在等待期限内未就绪"
                ) from None
        finally:
            if session is not None:
                session.release()
            pool.close()
        sleep(1)


class NebulaTarget:
    def __init__(self, credentials: Path, *, max_relations: int = 10_000) -> None:
        if max_relations < 1:
            raise ValueError("人物关系构建预算必须为正数")
        self.credentials = credentials
        self.max_relations = max_relations

    def build_and_verify(self, projection: Projection, context: BuildContext) -> GraphReceipt:
        try:
            return self._build(projection, context)
        except UpdateError:
            raise
        except Exception as error:
            # SDK包含未类型化网络／认证异常，在外部依赖边界统一转换并保留cause。
            raise UpdateError("GRAPH_BUILD_FAILED", "图目标构建失败，候选未激活") from error

    def _build(self, projection: Projection, context: BuildContext) -> GraphReceipt:
        nodes = cast(list[dict[str, Any]], projection.nodes)
        facts = cast(list[dict[str, Any]], projection.facts)
        if estimate(facts) > self.max_relations:
            raise UpdateError("RELATION_BUILD_LIMIT", "关系证据估计超过当前构建预算")
        space = "relationship_lab_sync_" + uuid4().hex[:12]
        # 外部资源创建前保存本次意图，失败也能追溯并只回收本次资源。
        write_json(context.directory / "build-resource.json", {"backend": "nebula", "space": space})
        meta = dict(
            schema_version=projection.model,
            projection_id=context.version,
            snapshot_sha256=context.source_digest,
            reference_month=context.reference_month,
            state="staging",
        )
        root = Path(__file__).resolve().parents[4]
        with connect(load_credentials(self.credentials)) as session:
            query(
                session,
                f"CREATE SPACE `{space}` "
                "(partition_num=1,replica_factor=1,vid_type=FIXED_STRING(128))",
            )
            query(session, f"USE `{space}`", wait=True)
            for statement in schema_statements(root):
                query(session, statement, wait=True)
            writer = ProjectionWriter(session)
            writer.vertices(
                "projection_meta", list(meta), [("meta:projection", list(meta.values()))]
            )
            insert_nodes(writer, nodes)
            insert_edges(writer, facts)
            targets = {fact["target"] for fact in facts}
            relation_nodes = [node for node in nodes if node["vid"] in targets]
            relations = calculate_relations(
                session, relation_nodes, context.reference_month, max_relations=self.max_relations
            )
            edges = facts + relations
            insert_edges(writer, relations)

            def bounded(statement: str, maximum: int) -> list[dict]:
                records = query(session, statement)
                if len(records) > maximum:
                    raise UpdateError("GRAPH_INTEGRITY", "图回读超出预期范围")
                return records

            actual = read_all(
                bounded, nodes, max_rows_per_query=max(self.max_relations, len(facts))
            )
            expected = graph_digest(nodes, edges)
            if graph_digest(*actual) != expected:
                raise UpdateError("GRAPH_INTEGRITY", "新图完整回读不符")
            reader = _reader_account(session, context.directory)
            query(session, f"GRANT ROLE GUEST ON `{space}` TO {reader.username}")
            meta["state"] = "ready"
            writer.vertices(
                "projection_meta", list(meta), [("meta:projection", list(meta.values()))]
            )
            stored = query(
                session,
                'FETCH PROP ON projection_meta "meta:projection" YIELD properties(vertex) AS meta',
            )
            if stored != [{"meta": meta}]:
                raise UpdateError("GRAPH_INTEGRITY", "新图完成标记回读不符")
        verify_reader(reader, space, meta)
        return GraphReceipt(
            backend="nebula",
            space=space,
            graph_digest=expected,
            node_count=len(nodes),
            fact_count=len(facts),
            relation_count=len(relations),
        )
