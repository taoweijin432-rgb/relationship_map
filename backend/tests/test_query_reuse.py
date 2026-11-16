"""页装配只读一次事实与完整证据；保留独立SQL模式和画布额度语义。"""

from dataclasses import asdict
from unittest.mock import patch

import pytest

from relationship_query.contracts import ExpandRequest, ExportRequest, SearchRequest
from relationship_query.services.graph import build_graph


@pytest.mark.parametrize("reference", [None, "p:000001"])
def test_export_reuses_complete_page_facts_and_proofs(client, reference):
    service = client.app.state.query_service
    request = SearchRequest(page_size=20)
    page = service.search(request, reference)
    with (
        patch.object(service, "_proofs", wraps=service._proofs) as proofs,
        patch.object(
            service.repository, "fact_views", wraps=service.repository.fact_views
        ) as facts,
    ):
        exported = service.export_page(
            ExportRequest(
                reference_id=reference,
                filters=request,
                data_version=page.data_version,
                expected_person_ids=[item.person.id for item in page.items],
            )
        )
    assert facts.call_count == 1
    assert proofs.call_count == int(reference is not None)
    assert [item.person for item in exported.items] == [item.person for item in page.items]
    for item in exported.items:
        assert item.facts == service.repository.fact_views([item.person.id])
        if reference:
            assert item.evidence == service.evidence(reference, item.person.id, request).items


@pytest.mark.parametrize("known", ["none", "partial", "nodes_full", "edges_full"])
def test_expand_reuses_untrimmed_facts_and_preserves_canvas_limits(client, known):
    service = client.app.state.query_service
    request = SearchRequest(page_size=20)
    reference = "p:000001"
    page = service._direct_page(request, reference)
    nodes = page.response.graph.nodes
    edges = page.response.graph.edges
    known_nodes = {
        "none": [],
        "partial": [node.id for node in nodes[:5]],
        "nodes_full": [reference] + [f"existing:{i}" for i in range(99)],
        "edges_full": [],
    }[known]
    known_edges = (
        [f"edge:existing:{i}" for i in range(200)]
        if known == "edges_full"
        else [edge.id for edge in edges[:3]]
        if known == "partial"
        else []
    )
    assert page.response.reference is not None
    expected = build_graph(
        [page.response.reference, *[item.person for item in page.response.items]],
        page.graph_facts,
        reference,
        known_nodes,
        known_edges,
    )
    with (
        patch.object(service, "_proofs", wraps=service._proofs) as proofs,
        patch.object(
            service.repository, "fact_views", wraps=service.repository.fact_views
        ) as facts,
    ):
        result = service.expand(
            ExpandRequest(
                person_id=reference,
                filters=request,
                existing_node_ids=known_nodes,
                existing_edge_ids=known_edges,
            )
        )
    assert facts.call_count == proofs.call_count == 1
    assert result.graph.nodes == expected.nodes
    assert result.graph.edges == expected.edges
    assert len(result.graph.nodes) + len(known_nodes) <= 100
    assert len(result.graph.edges) + len(known_edges) <= 200
    assert result.graph.truncated == (expected.truncated or page.response.has_more)


def test_id_plan_contains_no_person_display_or_evidence(client):
    service = client.app.state.query_service
    plan = service.select_page(SearchRequest(page_size=2), "p:000001")
    assert len(plan.ids) == 2 and plan.has_more
    assert set(asdict(plan)) == {
        "data_version",
        "reference_month",
        "reference_id",
        "fingerprint",
        "ids",
        "has_more",
        "next_cursor",
        "query_key",
        "chains",
        "probe_id",
    }
    assert plan.data_version == service.repository.version
    assert plan.reference_id == "p:000001"
