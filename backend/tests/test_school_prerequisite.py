"""可选同校前提按每段人物关系生效，兼容既有查询指纹。"""

import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from relationship_query.contracts import RelationScope, SearchRequest
from relationship_query.infrastructure.uuid_graph import connection_match, proof_query
from relationship_query.services.query import QueryService


@pytest.mark.parametrize("value", [1, "true", None])
def test_school_flag_is_strict_boolean(value):
    with pytest.raises(ValidationError):
        RelationScope(relation_type="same_major", require_same_school=value)


@pytest.mark.parametrize("kind", [None, "same_school", "same_company", "same_company_overlap"])
def test_school_flag_requires_major(kind):
    with pytest.raises(ValidationError):
        RelationScope(relation_type=kind, require_same_school=True)


@pytest.mark.parametrize("depth", [1, 2, 3, 4])
def test_every_hop_requires_school(depth):
    scope = SearchRequest(relation_type="same_major", require_same_school=True)
    statement, _ = connection_match("p:expert:1", scope, depth)
    for index in range(depth):
        assert f", (v{index})-[:same_school]-(v{index + 1})" in statement
    assert statement.count("[:same_school]") == depth
    plain, _ = connection_match("p:expert:1", SearchRequest(relation_type="same_major"), depth)
    assert "[:same_school]" not in plain


def test_proof_deduplicates_multiple_school_witnesses():
    scope = RelationScope(relation_type="same_major", require_same_school=True)
    statement = proof_query("same_major", scope, "p:expert:1", "p:expert:2", 21)
    assert ", (a)-[:same_school]-(b)" in statement
    assert "RETURN DISTINCT" in statement
    assert statement.endswith("LIMIT 21")


def test_default_cursor_is_compatible_and_selected_flag_is_isolated():
    service = QueryService(SimpleNamespace(version="fixed"))
    request = SearchRequest(relation_type="same_major")
    legacy = {
        "filters": request.model_dump(
            exclude={
                "cursor",
                "page_size",
                "organization_id",
                "school_id",
                "role_id",
                "require_same_school",
            }
        ),
        "reference": "p:expert:1",
        "version": "fixed",
        "query_contract": "scoped-relations-v1",
    }
    fingerprint = service._fingerprint(request, "p:expert:1")
    assert fingerprint == hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    selected = service._fingerprint(
        request.model_copy(update={"require_same_school": True}), "p:expert:1"
    )
    assert selected != fingerprint
