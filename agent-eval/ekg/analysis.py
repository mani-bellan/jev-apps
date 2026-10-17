"""Turns scored runs into the EKG findings: where runs derail, how early failure is
visible, and what stopping low-scoring runs would save."""

from .jev import JEV_PRICE_PER_INPUT_TOKEN

THRESHOLDS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
MAX_FALSE_KILL = 0.10


def curve(run: dict) -> list[float]:
    """P(on track) after each tool step, then after the final answer."""
    return [s["on_track"] for s in run["scores"]]


def derail_point(run: dict, t: float = 0.5) -> int | None:
    """0-based index of the first point where P(on track) falls below t."""
    return next((i for i, p in enumerate(curve(run)) if p < t), None)


def kill_step(run: dict, t: float) -> int | None:
    """0-based tool step after which a monitor with threshold t would stop the run."""
    tool_points = curve(run)[: len(run["steps"])]
    return next((i for i, p in enumerate(tool_points) if p < t), None)


def auc(pos: list[float], neg: list[float]) -> float | None:
    """Probability that a random positive outranks a random negative (ties count half)."""
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def simulate_stop(runs: list[dict], t: float) -> dict:
    failed = [r for r in runs if not r["success"]]
    passed = [r for r in runs if r["success"]]
    total_tokens = sum(s["agent_tokens"] for r in runs for s in r["steps"]) or 1
    saved = 0
    for r in runs:
        k = kill_step(r, t)
        if k is not None:
            saved += sum(s["agent_tokens"] for s in r["steps"][k + 1:])
    caught = sum(kill_step(r, t) is not None for r in failed)
    false_kills = sum(kill_step(r, t) is not None for r in passed)
    return {
        "threshold": t,
        "caught": caught,
        "caught_rate": caught / len(failed) if failed else 0.0,
        "false_kills": false_kills,
        "false_kill_rate": false_kills / len(passed) if passed else 0.0,
        "tokens_saved_rate": saved / total_tokens,
        "wasted_tokens_saved_rate": (
            sum(sum(s["agent_tokens"] for s in r["steps"][k + 1:])
                for r in failed if (k := kill_step(r, t)) is not None)
            / (sum(s["agent_tokens"] for r in failed for s in r["steps"]) or 1)
        ),
    }


def analyze(runs: list[dict]) -> dict:
    failed = [r for r in runs if not r["success"]]
    passed = [r for r in runs if r["success"]]
    stops = [simulate_stop(runs, t) for t in THRESHOLDS]
    eligible = [s for s in stops if s["false_kill_rate"] <= MAX_FALSE_KILL]
    best = max(eligible, key=lambda s: (s["caught_rate"], -s["threshold"])) if eligible else min(
        stops, key=lambda s: s["false_kill_rate"])

    max_steps = max((len(r["steps"]) for r in runs), default=0)
    by_step = []
    for k in range(1, max_steps + 1):
        def flagged(r):
            ks = kill_step(r, best["threshold"])
            return ks is not None and ks < k

        def risk(r):  # what we know after k actions: the k-th point, or the final one if the run ended
            c = curve(r)
            return 1 - c[min(k, len(r["steps"])) - 1] if r["steps"] else 1 - c[-1]

        by_step.append({
            "step": k,
            "caught_rate": sum(map(flagged, failed)) / len(failed) if failed else 0.0,
            "false_alarm_rate": sum(map(flagged, passed)) / len(passed) if passed else 0.0,
            "auc": auc([risk(r) for r in failed], [risk(r) for r in passed]),
        })

    derails = [d for r in failed if (d := derail_point(r)) is not None]
    final_auc = auc([1 - curve(r)[-1] for r in failed], [1 - curve(r)[-1] for r in passed])
    jev_tokens = sum(s["jev_input_tokens"] for r in runs for s in r["scores"])
    return {
        "runs": len(runs),
        "passed": len(passed),
        "failed": len(failed),
        "stops": stops,
        "best": best,
        "by_step": by_step,
        "median_derail_step": sorted(derails)[len(derails) // 2] + 1 if derails else None,
        "final_auc": final_auc,
        "jev_calls": sum(len(r["scores"]) for r in runs),
        "jev_cost_usd": jev_tokens * JEV_PRICE_PER_INPUT_TOKEN,
    }
