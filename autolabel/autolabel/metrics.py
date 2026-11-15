"""Accuracy, calibration and "how much can it label on its own" for one labeling task.

Every method gives, per complaint, a probability for each option. Its confidence is the top option's probability.
A method labels a complaint on its own when its confidence clears a threshold; the rest go to a person."""

import random


def normalize(probs: dict) -> dict:
    total = sum(probs.values()) or 1.0
    return {k: v / total for k, v in probs.items()}


def scored(answers: list[dict], gold: list[str]) -> list[tuple[float, bool, dict]]:
    """(confidence, correct, probabilities) per complaint."""
    out = []
    for a, y in zip(answers, gold):
        p = normalize(a["probabilities"])
        top = max(p, key=p.get)
        out.append((p[top], top == y, p))
    return out


def accuracy(rows) -> float:
    return sum(c for _, c, _ in rows) / len(rows)


def brier(rows, gold) -> float:
    """Multi-class Brier score: squared error of the whole probability vector, averaged. Lower is better."""
    return sum(sum((v - (k == y)) ** 2 for k, v in p.items()) for (_, _, p), y in zip(rows, gold)) / len(rows)


def ece(rows, bins: int = 10) -> float:
    """Expected calibration error of the confidence: the average gap between how sure it said it was and how often
    it was right, weighted by how many complaints fall in each confidence bin."""
    buckets = [[] for _ in range(bins)]
    for conf, correct, _ in rows:
        buckets[min(int(conf * bins), bins - 1)].append((conf, correct))
    return sum(abs(sum(c for c, _ in b) / len(b) - sum(k for _, k in b) / len(b)) * len(b)
               for b in buckets if b) / len(rows)


def reliability(rows, bins: int = 10) -> list[dict]:
    buckets = [[] for _ in range(bins)]
    for conf, correct, _ in rows:
        buckets[min(int(conf * bins), bins - 1)].append((conf, correct))
    return [{"lo": i / bins, "hi": (i + 1) / bins, "n": len(b),
             "confidence": sum(c for c, _ in b) / len(b), "accuracy": sum(k for _, k in b) / len(b)}
            for i, b in enumerate(buckets) if b]


def at_threshold(rows, t: float) -> dict:
    kept = [c for conf, c, _ in rows if conf >= t]
    return {"threshold": t, "coverage": len(kept) / len(rows), "kept": len(kept),
            "accuracy": sum(kept) / len(kept) if kept else None}


def curve(rows) -> list[tuple[float, float]]:
    """(coverage, accuracy of the kept complaints) as the threshold goes down from the most confident complaint."""
    ordered = sorted(rows, key=lambda r: -r[0])
    out, right = [], 0
    for i, (conf, correct, _) in enumerate(ordered, 1):
        right += correct
        if i == len(ordered) or ordered[i][0] != conf:  # ties share one point
            out.append((i / len(ordered), right / i))
    return out


def tune_threshold(rows, target: float) -> float:
    """Lowest confidence threshold whose kept complaints are at least `target` accurate on these rows.
    Returns 1.01 (label nothing) when no threshold reaches the target."""
    ordered = sorted(rows, key=lambda r: -r[0])
    best, right = 1.01, 0
    for i, (conf, correct, _) in enumerate(ordered, 1):
        right += correct
        if (i == len(ordered) or ordered[i][0] != conf) and right / i >= target:
            best = conf
    return best


def bootstrap(rows, stat, n: int = 1000, seed: int = 7) -> tuple[float, float]:
    """95% interval of `stat(rows)` over resampled complaints."""
    rng = random.Random(seed)
    vals = sorted(stat([rng.choice(rows) for _ in rows]) for _ in range(n))
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]
