from ..models import Claim
from .common import normalise, prf


def evaluate_propositions(predicted: list[Claim], gold: list[Claim]) -> dict:
    pred = {(c.evidence_id, c.source.source_span.start_char, c.source.source_span.end_char,
             normalise(c.proposition_text)) for c in predicted}
    ref = {(c.evidence_id, c.source.source_span.start_char, c.source.source_span.end_char,
            normalise(c.proposition_text)) for c in gold}
    traceable = sum(bool(c.evidence_id and c.span_id and c.source.source_span.text) for c in predicted)
    return {"stage": "propositionalisation", "exact_proposition": prf(pred, ref),
            "traceability_completeness": traceable / len(predicted) if predicted else 1.0,
            "manual_review_required": ["faithfulness", "atomicity", "self_containedness",
                                       "modality", "negation", "unsupported_information"]}
