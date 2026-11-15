"""The classic alternative: a TF-IDF + logistic regression classifier trained on labeled complaints.

Two sizes: one trained on the 440 tune complaints (as many labels as the decision models get to set their
thresholds with), and one trained on about 21,700 more. Answers come back in the decision models' shape
({"choice", "probabilities"}) so the same metrics apply. The issue classifier is trained per product and, like the
decision models, is told the true product."""

from collections import defaultdict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline


def _model(n_train: int):
    return make_pipeline(TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=2 if n_train > 2000 else 1,
                                         max_features=50_000),
                         LogisticRegression(max_iter=1000, C=4.0))


def _fit_predict(train: list[dict], test: list[dict], field: str, options: list[str]) -> list[dict]:
    labels = {r[field] for r in train}
    if len(labels) == 1:
        only = labels.pop()
        return [{"choice": only, "probabilities": {o: float(o == only) for o in options}} for _ in test]
    m = _model(len(train)).fit([r["text"] for r in train], [r[field] for r in train])
    out = []
    for probs in m.predict_proba([r["text"] for r in test]):
        p = {o: 0.0 for o in options}
        p.update(dict(zip(m.classes_, map(float, probs))))
        out.append({"choice": max(p, key=p.get), "probabilities": p})
    return out


def _both(train: list[dict], test: list[dict], tax: dict) -> list[dict]:
    product = _fit_predict(train, test, "product", list(tax))
    issue = [None] * len(test)
    train_by, test_by = defaultdict(list), defaultdict(list)
    for r in train:
        train_by[r["product"]].append(r)
    for i, r in enumerate(test):
        test_by[r["product"]].append(i)
    for p, idx in test_by.items():
        for i, ans in zip(idx, _fit_predict(train_by[p], [test[i] for i in idx], "issue", list(tax[p]))):
            issue[i] = ans
    return [{"product": a, "issue": b} for a, b in zip(product, issue)]


def predict(train: list[dict], splits: dict[str, list[dict]], tax: dict, oof_split: str | None = None) -> dict:
    """Answers for each split. For `oof_split` (the split the classifier trains on), answers are out-of-fold
    from 5-fold cross-validation, so thresholds are never set on answers about the training data itself."""
    out = {}
    for name, rows in splits.items():
        if name != oof_split:
            out[name] = _both(train, rows, tax)
            continue
        answers = [None] * len(rows)
        for tr, te in KFold(5, shuffle=True, random_state=7).split(rows):
            for i, a in zip(te, _both([rows[i] for i in tr], [rows[i] for i in te], tax)):
                answers[i] = a
        out[name] = answers
    return out
