from relationship_query.contracts import FactView, GraphData, GraphEdge, GraphNode
from relationship_query.domain.models import Person
from relationship_query.runtime.diagnostics import traced

MAX_NODES = 100
MAX_EDGES = 200


@traced("build_graph")
def build_graph(
    persons: list[Person],
    fact_views: list[FactView],
    reference_id: str | None,
    existing_node_ids: list[str] | None = None,
    existing_edge_ids: list[str] | None = None,
) -> GraphData:
    known_nodes = set(existing_node_ids or [])
    known_edges = set(existing_edge_ids or [])
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    truncated = False
    for person in persons:
        if person.id not in known_nodes and len(known_nodes) + len(nodes) >= MAX_NODES:
            truncated = True
            continue
        if person.id not in known_nodes:
            nodes[person.id] = GraphNode(
                id=person.id,
                type="person",
                label=person.name,
                is_reference=person.id == reference_id,
            )
    present = known_nodes | nodes.keys()
    for view in fact_views:
        if view.fact.person_id not in present:
            continue
        edge_id = f"edge:{view.fact.id}"
        if edge_id in known_edges or edge_id in edges:
            continue
        new_entity = view.entity.id not in present
        if (
            new_entity
            and len(known_nodes) + len(nodes) >= MAX_NODES
            or len(known_edges) + len(edges) >= MAX_EDGES
        ):
            truncated = True
            continue
        if new_entity:
            nodes[view.entity.id] = GraphNode(
                id=view.entity.id,
                type="organization"
                if view.entity.type == "organization"
                else ("major" if view.entity.type == "major" else "school"),
                label=view.entity.name,
            )
            present = known_nodes | nodes.keys()
        edges[edge_id] = GraphEdge(
            id=edge_id,
            source=view.fact.person_id,
            target=view.entity.id,
            label={"employment": "任职", "education": "就读", "major": "所学专业"}[view.fact.type],
            fact_id=view.fact.id,
        )
    return GraphData(
        nodes=list(nodes.values()),
        edges=list(edges.values()),
        truncated=truncated,
        truncation_reason="已达到画布节点或边数量上限，列表仍可完整翻页" if truncated else None,
    )
