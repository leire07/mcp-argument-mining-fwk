def prf(predicted: set, gold: set) -> dict[str, float | int]:
    true_positive = len(predicted & gold)
    precision = true_positive / len(predicted) if predicted else (1.0 if not gold else 0.0)
    recall = true_positive / len(gold) if gold else (1.0 if not predicted else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"true_positive": true_positive, "predicted": len(predicted), "gold": len(gold),
            "precision": precision, "recall": recall, "f1": f1}


def normalise(text: str) -> str:
    return " ".join(text.casefold().split())
