"""三表方案独立图验收；不发布为当前 API 的 format_version=1 投影。"""

import json
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from nebula3.Config import Config  # type: ignore[import-untyped]
from nebula3.Exception import AuthFailedException  # type: ignore[import-untyped]
from nebula3.gclient.net import ConnectionPool  # type: ignore[import-untyped]

from relationship_query.contracts import RelationScope
from relationship_query.domain.models import RelationType
from relationship_query.infrastructure.graph_model import ReaderCredentials, literal
from relationship_query.infrastructure.graph_projection import ProjectionWriter, _reader_account
from relationship_query.infrastructure.graph_relation_queries import _pair
from relationship_query.infrastructure.nebula_lab import (
    DEFAULT_CREDENTIALS,
    connect,
    load_credentials,
    query,
)
from relationship_query.infrastructure.projection_source_schema import MAPPING, SLOTS

EDGE_SCHEMA = (
    "fact_id string, kind string, active bool, start_date int, end_date int, is_current bool, "
    "role_id int, source_system string, source_record_id string, source_table string, "
    "source_field_id int, source_field string"
)


@contextmanager
def reader_session(config: ReaderCredentials) -> Iterator[Any]:
    deadline = monotonic() + 60
    while True:
        pool, session = ConnectionPool(), None
        options = Config()
        options.timeout, options.max_connection_pool_size = 15000, 1
        try:
            if not pool.init([(config.host, config.port)], options):
                raise RuntimeError("实验图连接未就绪")
            session = pool.get_session(config.username, config.password.get_secret_value())
        except AuthFailedException:
            pool.close()
            if monotonic() >= deadline:
                raise RuntimeError("新只读账号未在限时内生效") from None
            sleep(1)
            continue
        except Exception:
            pool.close()
            raise
        break
    try:
        yield session
    finally:
        session.release()
        pool.close()


def project_graph(
    nodes: list[dict], edges: list[dict], output: Path, digest: str
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    space = "relationship_lab_three_" + secrets.token_hex(6)
    types = sorted({edge for fields in SLOTS.values() for edge in fields.values()})
    with connect(load_credentials(DEFAULT_CREDENTIALS)) as session:
        query(
            session,
            f"CREATE SPACE `{space}` (partition_num=1,replica_factor=1,vid_type=FIXED_STRING(128))",
        )
        query(session, f"USE `{space}`", wait=True)
        for statement in (
            "CREATE TAG lab_projection(status string,digest string)",
            "CREATE TAG person(id string,name string,active bool)",
            "CREATE TAG entity(id int,kind string,name string)",
            *[f"CREATE EDGE `{kind}` ({EDGE_SCHEMA})" for kind in types],
        ):
            query(session, statement, wait=True)
        writer = ProjectionWriter(session)
        writer.vertices(
            "lab_projection", ["status", "digest"], [("meta|projection", ["building", digest])]
        )
        writer.vertices(
            "person",
            ["id", "name", "active"],
            [(n["vid"], [n["vid"], n["name"], True]) for n in nodes if n["type"] == "person"],
        )
        writer.vertices(
            "entity",
            ["id", "kind", "name"],
            [
                (n["vid"], [int(n["vid"].split(":")[1]), n["type"], n["name"]])
                for n in nodes
                if n["type"] != "person"
            ],
        )
        for kind in types:
            group = [e for e in edges if e["type"] == kind]
            if group:
                columns = list(group[0]["properties"])
                writer.edges(
                    "`" + kind + "`",
                    columns,
                    [
                        (e["source"], e["target"], e["rank"], [e["properties"][c] for c in columns])
                        for e in group
                    ],
                )
        credentials = _reader_account(session, output)
        query(session, f"GRANT ROLE GUEST ON `{space}` TO {credentials.username}")
        writer.vertices(
            "lab_projection", ["status", "digest"], [("meta|projection", ["ready", digest])]
        )
    with reader_session(credentials) as reader:
        query(reader, f"USE `{space}`")
        verify_nodes(reader, nodes)
        actual = []
        people = [n["vid"] for n in nodes if n["type"] == "person"]
        for offset in range(0, len(people), 16):
            start = ",".join(literal(p) for p in people[offset : offset + 16])
            for kind in types:
                found = query(
                    reader,
                    f"GO FROM {start} OVER `{kind}` "
                    "YIELD src(edge) AS source,dst(edge) AS target,rank(edge) AS rank,"
                    f"properties(edge) AS properties,{literal(kind)} AS type LIMIT [513]",
                )
                if len(found) > 512:
                    raise ValueError("实验回读超过边界")
                actual.extend(found)

        def key(edge: dict) -> tuple:
            return edge["source"], edge["target"], edge["type"], edge["rank"]

        if sorted(actual, key=key) != sorted(edges, key=key):
            raise ValueError("独立图回读对账失败，不发布实验清单")
    return dict(
        space=space,
        reader=credentials.username,
        format="source-slot-lab-v2",
        nodes=len(nodes),
        edges=len(edges),
        source_digest=digest,
        warning="仅独立实验；不能配置为现有 API 图投影",
    )


def verify_nodes(session: Any, nodes: list[dict]) -> None:
    for tag in ("person", "entity"):
        selected = [n for n in nodes if (n["type"] == "person") == (tag == "person")]
        for offset in range(0, len(selected), 32):
            batch = selected[offset : offset + 32]
            ids = ",".join(literal(n["vid"]) for n in batch)
            rows = query(
                session,
                f"FETCH PROP ON {tag} {ids} "
                "YIELD id(vertex) AS vid,properties(vertex) AS properties",
            )
            expected = {
                n["vid"]: (
                    dict(id=n["vid"], name=n["name"], active=True)
                    if tag == "person"
                    else dict(id=int(n["vid"].split(":")[1]), kind=n["type"], name=n["name"])
                )
                for n in batch
            }
            if {r["vid"]: r["properties"] for r in rows} != expected:
                raise ValueError("实验人物／实体顶点回读不一致")


def direct_proofs(
    session: Any, left: str, right: str, kind: RelationType = "same_company_overlap"
) -> list[dict]:
    scope = RelationScope(relation_type=kind)
    statement = _pair(scope, 202611, "id(a)==" + literal(left), "id(b)==" + literal(right))
    edge = "studied_at" if kind == "same_school" else "worked_at"
    statement = (
        statement.replace(":experience", f":{edge}")
        .replace(".start_month", ".start_date")
        .replace(".end_month", ".end_date")
    )
    return query(
        session,
        statement + "RETURN rank(x) AS left_rank,rank(y) AS right_rank,"
        "id(a) AS left_person,id(b) AS right_person,id(e) AS entity,"
        "CASE WHEN overlapping THEN lo ELSE NULL END AS start_month,"
        "CASE WHEN overlapping THEN hi ELSE NULL END AS end_month,"
        "CASE WHEN overlapping THEN months ELSE NULL END AS months "
        "ORDER BY left_rank,right_rank LIMIT 101",
    )


def verify_business(manifest: dict, snapshot: dict, output: Path) -> dict[str, Any]:
    credentials = ReaderCredentials.model_validate_json(
        (output / "reader-credentials.json").read_text()
    )
    with reader_session(credentials) as reader:
        query(reader, f"USE `{manifest['space']}`")
        overlap = direct_proofs(reader, "p:expert:1", "p:resume:2")
        assert [r["months"] for r in overlap] == [24]
        assert not direct_proofs(reader, "p:expert:1", "p:resume:3")
        assert not direct_proofs(reader, "p:expert:1", "p:resume:4")
        nonoverlap = direct_proofs(reader, "p:expert:1", "p:resume:3", "same_company")
        assert len(nonoverlap) == 2 and all(r["months"] is None for r in nonoverlap)
        schools = direct_proofs(reader, "p:expert:1", "p:resume:2", "same_school")
        assert schools and all(r["months"] is None for r in schools)
        first = _pair(
            RelationScope(relation_type="same_company_overlap"),
            202611,
            'id(a)=="p:expert:1"',
            'id(b) NOT IN ["p:expert:1","p:resume:8"]',
            bounded_endpoints=False,
        )
        first = (
            first.replace(":experience", ":worked_at")
            .replace(".start_month", ".start_date")
            .replace(".end_month", ".end_date")
        )
        candidates = query(
            reader, first + "RETURN DISTINCT id(b) AS middle ORDER BY middle LIMIT 65"
        )
        if len(candidates) > 64:
            raise ValueError("实验候选超过核对边界")
        paths = []
        for candidate in candidates:
            middle = candidate["middle"]
            second = direct_proofs(reader, middle, "p:resume:8")
            if second:
                paths.append(
                    dict(
                        middle=middle,
                        first=direct_proofs(reader, "p:expert:1", middle),
                        second=second,
                    )
                )
        assert [p["middle"] for p in paths] == ["p:resume:7"]
        assert [p["months"] for p in paths[0]["first"]] == [24]
        assert [p["months"] for p in paths[0]["second"]] == [71]
    mappings = {m["id"]: m for m in snapshot[MAPPING]}
    for proof in [*overlap, *paths[0]["first"], *paths[0]["second"]]:
        for side in ("left", "right"):
            mapping = mappings[proof[side + "_rank"]]
            original = next(
                r
                for r in snapshot[mapping["source_table"]]
                if r["id"] == mapping["source_field_id"]
            )
            if original[mapping["source_system"] + "_id"] != int(
                proof[side + "_person"].split(":")[-1]
            ):
                raise ValueError("图证据的来源人物归属不一致")
    result = dict(
        overlap=overlap,
        nonoverlap=nonoverlap,
        schools=schools,
        paths=paths,
        evidence_source_rows_verified=True,
        graph_computes_time=True,
    )
    (output / "business-checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result
