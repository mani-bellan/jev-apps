"""Two cheap baselines that Jev has to beat to be worth calling."""

import re

from .extract import link_domains, sender_kind

RED_FLAGS = {
    "threat": r"block|suspend|deactivat|disconnect|expir|band ho|cancel|legal action|penalty|fine\b|challan",
    "urgency": r"urgent|immediately|today|tonight|within \d+|last chance|turant|abhi|jaldi|asap|final (notice|attempt)",
    "reward": r"won|winner|prize|lottery|lucky|reward|cashback|refund|gift|free|bonus|kbc|jackpot",
    "money": r"loan|pre-?approved|earn|income|profit|return|part[- ]time|work from home|task|invest|ipo|crypto",
    "credential": r"\bkyc\b|\bpan\b|aadhaa?r|otp|pin\b|password|cvv|card details|bank details|verify|update",
    "action": r"click|call now|call on|dial|whatsapp|install|download|\bapk\b|tap|link|pay\b|send",
}


def rules(record: dict) -> str:
    text = record["text"].lower()
    hits = sum(bool(re.search(p, text)) for p in RED_FLAGS.values())
    if link_domains(record["text"]) and not sender_kind(record.get("sender")).startswith("registered"):
        hits += 1
    return "scam" if hits >= 3 else "safe"


def tfidf(records: list[dict]) -> list[str] | None:
    """Out-of-fold predictions from a word + character n-gram logistic regression (5-fold cross-validation),
    so every message is predicted by a model that never saw it. Returns None when a set is too small to split."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline, make_union

    y = [r["label"] == "scam" for r in records]
    if min(sum(y), len(y) - sum(y)) < 5:
        return None
    model = make_pipeline(
        make_union(TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True),
                   TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)),
        LogisticRegression(max_iter=2000, class_weight="balanced"),
    )
    pred = cross_val_predict(model, [r["text"] for r in records], y, cv=StratifiedKFold(5, shuffle=True, random_state=7))
    return ["scam" if p else "safe" for p in pred]
