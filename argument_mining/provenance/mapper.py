from ..errors import ProvenanceError
from ..models import ArgumentRelation, Claim, EvidenceRecord


def validate_claims(claims: list[Claim], evidence_by_id: dict[str, EvidenceRecord]) -> None:
    seen = set()
    for claim in claims:
        if claim.claim_id in seen:
            raise ProvenanceError(f"claim_id duplicado: {claim.claim_id}")
        seen.add(claim.claim_id)
        evidence = evidence_by_id.get(claim.evidence_id)
        if evidence is None or claim.source.evidence_id != claim.evidence_id:
            raise ProvenanceError(f"Claim {claim.claim_id} sin evidence_id válido")
        span = claim.source.source_span
        if evidence.passage_text[span.start_char:span.end_char] != span.text:
            raise ProvenanceError(f"Offsets inválidos en {claim.claim_id}")


def build_provenance_map(claims: list[Claim], relations: list[ArgumentRelation],
                         evidence_by_id: dict[str, EvidenceRecord]) -> dict:
    by_claim = {claim.claim_id: claim for claim in claims}
    return {
        "schema_version": "1.0",
        "claims": [{
            "claim_id": claim.claim_id,
            "evidence_id": claim.evidence_id,
            "span_id": claim.span_id,
            "source_span": claim.source.source_span.model_dump(),
            "passage_text": claim.source.passage_text,
            "document": claim.source.document,
            "retrieval_provenance": claim.source.retrieval_provenance,
            "upstream_assessments": claim.source.upstream_assessments,
            "argument_mining_module": claim.generated_by.model_dump() if claim.generated_by else None,
        } for claim in claims],
        "relations": [{
            "relation_id": relation.relation_id,
            "source_claim_id": relation.source_claim_id,
            "target_claim_id": relation.target_claim_id,
            "source_evidence_id": by_claim[relation.source_claim_id].evidence_id,
            "target_evidence_id": by_claim[relation.target_claim_id].evidence_id,
            "argument_mining_module": relation.generated_by.model_dump() if relation.generated_by else None,
        } for relation in relations],
        "evidence_ids": sorted(evidence_by_id),
    }
