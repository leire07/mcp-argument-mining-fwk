from ..models import ArgumentSpan
from .common import prf


def evaluate_segmentation(predicted: list[ArgumentSpan], gold: list[ArgumentSpan]) -> dict:
    exact_pred = {(s.evidence_id, s.source_span.start_char, s.source_span.end_char) for s in predicted}
    exact_gold = {(s.evidence_id, s.source_span.start_char, s.source_span.end_char) for s in gold}
    matched_pred, matched_gold = set(), set()
    for pi, predicted_span in enumerate(predicted):
        candidates = []
        for gi, gold_span in enumerate(gold):
            if gi in matched_gold or predicted_span.evidence_id != gold_span.evidence_id:
                continue
            overlap = max(0, min(predicted_span.source_span.end_char, gold_span.source_span.end_char)
                          - max(predicted_span.source_span.start_char, gold_span.source_span.start_char))
            if overlap:
                union = max(predicted_span.source_span.end_char, gold_span.source_span.end_char) - min(
                    predicted_span.source_span.start_char, gold_span.source_span.start_char)
                candidates.append((overlap / union, gi))
        if candidates:
            _, gi = max(candidates)
            matched_pred.add(pi)
            matched_gold.add(gi)
    precision = len(matched_pred) / len(predicted) if predicted else (1.0 if not gold else 0.0)
    recall = len(matched_gold) / len(gold) if gold else (1.0 if not predicted else 0.0)
    relaxed = {"true_positive": len(matched_pred), "predicted": len(predicted), "gold": len(gold),
               "precision": precision, "recall": recall,
               "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}
    overlaps_by_gold = []
    for gold_span in gold:
        overlaps_by_gold.append(sum(
            candidate.evidence_id == gold_span.evidence_id
            and min(candidate.source_span.end_char, gold_span.source_span.end_char)
            > max(candidate.source_span.start_char, gold_span.source_span.start_char)
            for candidate in predicted
        ))
    overlaps_by_prediction = []
    for candidate in predicted:
        overlaps_by_prediction.append(sum(
            candidate.evidence_id == gold_span.evidence_id
            and min(candidate.source_span.end_char, gold_span.source_span.end_char)
            > max(candidate.source_span.start_char, gold_span.source_span.start_char)
            for gold_span in gold
        ))
    over_count = sum(max(0, count - 1) for count in overlaps_by_gold)
    under_count = sum(max(0, count - 1) for count in overlaps_by_prediction)
    return {
        "stage": "segmentation", "evaluation_reference": "gold",
        "exact_span": prf(exact_pred, exact_gold), "overlap_span": relaxed,
        "over_segmentation": {
            "count": over_count,
            "rate_per_gold_span": over_count / len(gold) if gold else 0.0,
            "definition": "extra predicted spans overlapping one gold span",
        },
        "under_segmentation": {
            "count": under_count,
            "rate_per_predicted_span": under_count / len(predicted) if predicted else 0.0,
            "definition": "extra gold spans overlapped by one predicted span",
        },
    }
