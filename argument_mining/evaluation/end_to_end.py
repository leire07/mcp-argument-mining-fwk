from ..models import ArgumentRelation, ArgumentSpan, Claim
from .propositions import evaluate_propositions
from .relations import evaluate_relations
from .segmentation import evaluate_segmentation


def evaluate_end_to_end(predicted_spans: list[ArgumentSpan], gold_spans: list[ArgumentSpan],
                        predicted_claims: list[Claim], gold_claims: list[Claim],
                        predicted_relations: list[ArgumentRelation], gold_relations: list[ArgumentRelation],
                        candidate_pairs: list[dict] | None = None) -> dict:
    """Aggregate frozen stage metrics without running or selecting any module."""
    traceable = sum(
        claim.source.passage_text[claim.source.source_span.start_char:claim.source.source_span.end_char]
        == claim.source.source_span.text for claim in predicted_claims
    )
    return {
        "evaluation_family": "end_to_end",
        "segmentation": evaluate_segmentation(predicted_spans, gold_spans),
        "propositionalisation": evaluate_propositions(predicted_claims, gold_claims),
        "relations": evaluate_relations(predicted_relations, gold_relations, candidate_pairs),
        "traceability_correctness": traceable / len(predicted_claims) if predicted_claims else 1.0,
    }
