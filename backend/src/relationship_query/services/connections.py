"""将图给出的完整人物链装配为逐段来源证据。"""

from relationship_query.contracts import ConnectionDetail, Evidence, PathSegment, SearchRequest
from relationship_query.domain.graph_relations import PROOF_PAIR_BATCH
from relationship_query.services.evidence import format_evidence, sort_evidence
from relationship_query.services.graph_paths import GraphPathService
from relationship_query.services.ports import MaterializedRelationReader
from relationship_query.services.query import QueryError


def connection_details(
    reader: MaterializedRelationReader,
    chains: dict[str, list[str]],
    request: SearchRequest,
    evidence_limit: int = 20,
    verify_person_ids: tuple[str, ...] = (),
) -> dict[str, ConnectionDetail]:
    ids = sorted({person for chain in chains.values() for person in chain} | set(verify_person_ids))
    people = reader.persons(ids) if ids else {}
    if set(people) != set(ids):
        raise QueryError("GRAPH_INTEGRITY", "连接链人物在配套SQL中缺失", 503)
    pairs = sorted({pair for chain in chains.values() for pair in zip(chain, chain[1:])})
    segments = {}
    for offset in range(0, len(pairs), PROOF_PAIR_BATCH):
        batch = pairs[offset : offset + PROOF_PAIR_BATCH]
        proofs = reader.read_proofs(request, batch, evidence_limit + 1)
        views = {
            view.fact.id: view
            for view in reader.fact_views_by_ids(
                sorted({fact for proof in proofs for fact in (proof.left_fact, proof.right_fact)})
            )
        }
        evidence: dict[tuple[str, str], list[Evidence]] = {pair: [] for pair in batch}
        for proof in proofs:
            if proof.left_fact not in views or proof.right_fact not in views:
                raise QueryError("GRAPH_INTEGRITY", "连接链事实在配套SQL中缺失", 503)
            GraphPathService._check_detail(proof, views)
            window = (
                (proof.start_month, proof.end_month, proof.months)
                if proof.start_month is not None
                and proof.end_month is not None
                and proof.months is not None
                else None
            )
            evidence[(proof.left_person, proof.right_person)].append(
                format_evidence(
                    views[proof.left_fact],
                    views[proof.right_fact],
                    proof.kind,
                    window,
                    require_same_school=request.require_same_school,
                    scoped=bool(
                        request.relation_start_month
                        or request.relation_end_month
                        or request.min_overlap_months
                    ),
                )
            )
        for left, right in batch:
            items = sort_evidence(evidence[(left, right)])
            if not items:
                raise QueryError("GRAPH_INTEGRITY", "连接链缺少对应的逐段证据", 503)
            segments[(left, right)] = PathSegment(
                id=f"segment:{left}|{right}",
                from_person=people[left],
                to_person=people[right],
                evidence=items[:evidence_limit],
                evidence_truncated=len(items) > evidence_limit,
            )
    return {
        candidate: ConnectionDetail(
            hop_count=len(chain) - 1,
            person_ids=chain,
            persons=[people[person] for person in chain],
            segments=[segments[pair] for pair in zip(chain, chain[1:])],
        )
        for candidate, chain in chains.items()
    }
