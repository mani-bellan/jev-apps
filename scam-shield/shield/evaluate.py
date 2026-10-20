"""Accuracy numbers for a labeled set, split by language."""

from statistics import median

from .jev import PRICE_PER_INPUT_TOKEN


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def metrics(rows: list[dict], verdict_key: str) -> dict:
    scams = [r for r in rows if r["label"] == "scam"]
    legit = [r for r in rows if r["label"] == "legit"]
    spam = [r for r in rows if r["label"] == "spam"]
    typed = [r for r in scams if r.get("scam_type")] if verdict_key.startswith("verdict") else []  # only Jev names types
    return {
        "n": len(rows), "scams": len(scams), "legit": len(legit), "spam": len(spam),
        # Of real scams, the share we warned about. "unsure" is neither caught nor missed.
        "catch_rate": _rate(sum(r[verdict_key] == "scam" for r in scams), len(scams)),
        "missed": _rate(sum(r[verdict_key] == "safe" for r in scams), len(scams)),
        # Of genuine messages, the share we wrongly called a scam. The number that gets a shield uninstalled.
        "false_alarms": _rate(sum(r[verdict_key] == "scam" for r in legit), len(legit)),
        "spam_flagged": _rate(sum(r[verdict_key] == "scam" for r in spam), len(spam)),
        "unsure": _rate(sum(r[verdict_key] == "unsure" for r in rows), len(rows)),
        "type_accuracy": _rate(sum(r["jev"]["scam_type"] == r["scam_type"] for r in typed), len(typed)),
    }


def summarize(rows: list[dict], methods: list[str]) -> dict:
    langs = ["all"] + sorted({r["lang"] for r in rows})
    out = {"by_method": {}}
    for m in methods:
        key = {"jev": "verdict", "jev-quick": "verdict_quick"}.get(m, f"baseline_{m}")
        out["by_method"][m] = {
            lang: metrics([r for r in rows if lang == "all" or r["lang"] == lang], key) for lang in langs
        }
    tokens = sum(r["input_tokens"] for r in rows)
    out["jev"] = {
        "input_tokens": tokens,
        "cost_usd": round(tokens * PRICE_PER_INPUT_TOKEN, 5),
        "tokens_per_message": round(tokens / len(rows)) if rows else 0,
        "median_latency_ms": median(r["latency_ms"] for r in rows) if rows else None,
    }
    return out


def fmt(x: float | None) -> str:
    return "   –" if x is None else f"{x:.2f}"


def print_table(stats: dict) -> None:
    for method, by_lang in stats["by_method"].items():
        print(f"\n{method}")
        print(f"  {'':<10}{'n':>6}  {'catch':>6}  {'missed':>6}  {'false alarms':>12}  {'unsure':>6}  {'type acc':>8}")
        for lang, m in by_lang.items():
            print(f"  {lang:<10}{m['n']:>6}  {fmt(m['catch_rate']):>6}  {fmt(m['missed']):>6}  "
                  f"{fmt(m['false_alarms']):>12}  {fmt(m['unsure']):>6}  {fmt(m['type_accuracy']):>8}")
