"""发布前只读回读核对；配置发布与停服版本切换复用。"""

from relationship_query.domain.path_budget import PathBudget
from relationship_query.infrastructure.graph_model import literal
from relationship_query.infrastructure.projection_source_schema import SLOTS
from relationship_query.infrastructure.source_api import SourceGraphClient


def verify_graph(client: SourceGraphClient, nodes: list[dict], edges: list[dict]) -> None:
    budget = PathBudget(60_000, 50_000)
    client.check_version(budget)
    for tag in ("person", "entity"):
        selected = [n for n in nodes if (n["type"] == "person") == (tag == "person")]
        for offset in range(0, len(selected), 64):
            batch = selected[offset : offset + 64]
            actual = client.fetch(tag, [n["vid"] for n in batch], budget)
            expected = {
                n["vid"]: {"id": n["vid"], "name": n["name"], "active": True}
                if tag == "person"
                else {
                    "id": int(n["vid"].split(":")[1]),
                    "kind": n["type"],
                    "name": n["name"],
                }
                for n in batch
            }
            if actual != expected:
                raise ValueError("API 发布前图顶点回读不一致")
    people = [n["vid"] for n in nodes if n["type"] == "person"]
    actual_edges = []
    for offset in range(0, len(people), 16):
        start = ",".join(literal(p) for p in people[offset : offset + 16])
        for kind in sorted({v for fields in SLOTS.values() for v in fields.values()}):
            rows = client.execute(
                f"GO FROM {start} OVER `{kind}` YIELD src(edge) AS source,dst(edge) AS target,"
                "rank(edge) AS rank,properties(edge) AS properties,"
                f"{literal(kind)} AS type LIMIT [513]",
                budget,
                513,
            )
            if len(rows) > 512:
                raise ValueError("API 发布回读批次超限，不截断发布")
            actual_edges.extend(rows)

    def key(edge: dict) -> tuple:
        return edge["source"], edge["target"], edge["type"], edge["rank"]

    if sorted(actual_edges, key=key) != sorted(edges, key=key):
        raise ValueError("API 发布前图边回读不一致")
    client.check_version(budget)
