from collections import Counter

from ..models import ArgumentRelation
from .common import prf


def evaluate_relations(predicted: list[ArgumentRelation], gold: list[ArgumentRelation],
                       candidate_pairs: list[dict] | None = None) -> dict:
    if candidate_pairs is not None:
        positive = {(r.source_claim_id, r.target_claim_id) for r in predicted if r.relation != "none"}
        predicted = [*predicted, *[
            ArgumentRelation(
                relation_id=f"none_{index}", source_claim_id=pair["source_claim_id"],
                target_claim_id=pair["target_claim_id"], relation="none", xaif_relation_type=None,
            )
            for index, pair in enumerate(candidate_pairs)
            if (pair["source_claim_id"], pair["target_claim_id"]) not in positive
        ]]
        gold_positive = {(r.source_claim_id, r.target_claim_id) for r in gold}
        gold = [*gold, *[
            ArgumentRelation(relation_id=f'gold_none_{index}',
                             source_claim_id=pair['source_claim_id'],
                             target_claim_id=pair['target_claim_id'],
                             relation='none', xaif_relation_type=None, input_kind='gold')
            for index, pair in enumerate(candidate_pairs)
            if (pair['source_claim_id'], pair['target_claim_id']) not in gold_positive
        ]]
    labels = ("support", "attack", "rephrase", "none")
    per_class, f1s = {}, []
    for label in labels:
        pred = {(r.source_claim_id, r.target_claim_id) for r in predicted if r.relation == label}
        ref = {(r.source_claim_id, r.target_claim_id) for r in gold if r.relation == label}
        per_class[label] = prf(pred, ref)
        if pred or ref:
            f1s.append(per_class[label]["f1"])
    predicted_by_pair = {(r.source_claim_id, r.target_claim_id): r.relation for r in predicted}
    gold_by_pair = {(r.source_claim_id, r.target_claim_id): r.relation for r in gold}
    universe = set(predicted_by_pair) | set(gold_by_pair)
    if candidate_pairs is not None:
        universe |= {(pair["source_claim_id"], pair["target_claim_id"]) for pair in candidate_pairs}
    confusion = {actual: {observed: 0 for observed in labels} for actual in labels}
    for pair in universe:
        actual, observed = gold_by_pair.get(pair, "none"), predicted_by_pair.get(pair, "none")
        confusion[actual][observed] += 1
    correct = sum(confusion[label][label] for label in labels)
    return {"stage": "relation_identification", "evaluation_reference": "gold",
            "per_class": per_class,
            "macro_f1": sum(f1s) / len(f1s) if f1s else 1.0, "directed": True,
            "directed_edge_accuracy": correct / len(universe) if universe else 1.0,
            "confusion_matrix": confusion, "evaluated_directed_pairs": len(universe),
            "predicted_distribution": dict(Counter(r.relation for r in predicted)),
            "gold_distribution": dict(Counter(r.relation for r in gold))}
