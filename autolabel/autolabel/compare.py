"""Compares every method on the held-out split. Thresholds are set on the tune split, separately for each method,
then applied unchanged to held-out."""

import json
from collections import Counter
from statistics import median

from . import baselines, metrics
from .data import load
from .deciders import BACKENDS
from .questions import taxonomy
from .run import RESULTS, read_results

TASKS = ["product", "issue"]
TARGETS = [0.85, 0.90, 0.95]
LABELS = {"jev": "Jev", "strands": "Strands Decider 2B", "tfidf-440": "Classifier, 440 labels",
          "tfidf-21k": "Classifier, 21,739 labels"}


def _decider_answers(backend: str, split: str, records: list[dict]) -> list[dict] | None:
    res = read_results(backend, split)
    if not all(r["id"] in res for r in records):
        return None
    return [res[r["id"]] for r in records]


def compare() -> dict:
    tax = taxonomy()
    tune, heldout = load("tune"), load("heldout")
    answers, calls = {}, {}
    for backend in BACKENDS:
        t, h = _decider_answers(backend, "tune", tune), _decider_answers(backend, "heldout", heldout)
        if t and h:
            answers[backend] = {"tune": [x["answers"] for x in t], "heldout": [x["answers"] for x in h]}
            calls[backend] = h
        else:
            print(f"  {backend}: skipped, run `autolabel run tune --backend {backend}` and `... heldout` first")
    cache = RESULTS / "baselines.json"  # the classifiers take a few minutes; delete this file to retrain them
    if cache.exists():
        answers.update(json.loads(cache.read_text()))
    else:
        splits = {"tune": tune, "heldout": heldout}
        trained = {"tfidf-440": baselines.predict(tune, splits, tax, oof_split="tune"),
                   "tfidf-21k": baselines.predict(load("train_large"), splits, tax)}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(trained))
        answers.update(trained)

    stats = {"meta": {"tune": len(tune), "heldout": len(heldout), "targets": TARGETS,
                      "products": len(tax), "issues": sum(map(len, tax.values()))},
             "methods": {}, "per_product": {}, "confusions": {}, "agreement": {}}
    scored = {}
    for m, ans in answers.items():
        entry = {"label": LABELS[m], "tasks": {}}
        for task in TASKS:
            gold_t, gold_h = [r[task] for r in tune], [r[task] for r in heldout]
            st = metrics.scored([a[task] for a in ans["tune"]], gold_t)
            sh = metrics.scored([a[task] for a in ans["heldout"]], gold_h)
            scored[(m, task)] = sh
            targets = {}
            for target in TARGETS:
                t = metrics.tune_threshold(st, target)
                h = metrics.at_threshold(sh, t)
                h["coverage_ci"] = metrics.bootstrap(sh, lambda rows, t=t: metrics.at_threshold(rows, t)["coverage"])
                targets[str(target)] = {"threshold": t, "tune": metrics.at_threshold(st, t), "heldout": h}
            entry["tasks"][task] = {
                "accuracy": metrics.accuracy(sh), "accuracy_ci": metrics.bootstrap(sh, metrics.accuracy),
                "brier": metrics.brier(sh, gold_h), "ece": metrics.ece(sh),
                "at_0.9_untuned": metrics.at_threshold(sh, 0.9), "targets": targets,
                "reliability": metrics.reliability(sh), "curve": metrics.curve(sh),
            }
        if m in calls:
            backend = BACKENDS[m]
            tokens = [c["input_tokens"] for c in calls[m]]
            entry["latency_ms_median"] = median(c["latency_ms"] for c in calls[m])
            entry["tokens_per_complaint"] = round(sum(tokens) / len(tokens))
            entry["model"] = calls[m][0]["model"]
            if backend.usd_per_million_input_tokens is not None:
                entry["usd_per_10k"] = sum(tokens) / len(tokens) * 10_000 * backend.usd_per_million_input_tokens / 1e6
        stats["methods"][m] = entry
        stats["per_product"][m] = {
            p: sum(c for (_, c, _), r in zip(scored[(m, "product")], heldout) if r["product"] == p)
            / sum(r["product"] == p for r in heldout) for p in tax}
        wrong = Counter((r["product"], a["product"]["choice"]) for r, a in zip(heldout, ans["heldout"])
                        if a["product"]["choice"] != r["product"])
        stats["confusions"][m] = [{"gold": g, "predicted": p, "n": n} for (g, p), n in wrong.most_common(8)]

    if "jev" in answers and "strands" in answers:
        for task in TASKS:
            j, s = scored[("jev", task)], scored[("strands", task)]
            jc = [a[task]["choice"] for a in answers["jev"]["heldout"]]
            sc = [a[task]["choice"] for a in answers["strands"]["heldout"]]
            agree = [i for i in range(len(heldout)) if jc[i] == sc[i]]
            differ = [i for i in range(len(heldout)) if jc[i] != sc[i]]
            # Complaints where the two decision models and the classifier trained on 21,739 consumer labels all give
            # the same answer, and it isn't the label the consumer chose: likely complaints filed under an odd label.
            cc = [a[task]["choice"] for a in answers["tfidf-21k"]["heldout"]]
            outvoted = [i for i in agree if jc[i] == cc[i] and jc[i] != heldout[i][task]]
            stats["agreement"][task] = {
                "all_three_overrule_label": len(outvoted),
                "agree_rate": len(agree) / len(heldout),
                "accuracy_when_agree": sum(j[i][1] for i in agree) / len(agree) if agree else None,
                "jev_right_when_differ": sum(j[i][1] for i in differ) / len(differ) if differ else None,
                "strands_right_when_differ": sum(s[i][1] for i in differ) / len(differ) if differ else None,
            }
    out = RESULTS / "compare"
    out.mkdir(parents=True, exist_ok=True)
    (out / "stats.json").write_text(json.dumps(stats, indent=2))
    return stats


def print_table(stats: dict) -> None:
    for task in TASKS:
        print(f"\n{task} (held-out, {stats['meta']['heldout']} complaints)")
        print(f"  {'':28} {'accuracy':>16} {'brier':>6} {'ece':>6}  {'conf >= 0.9 as is':>17}"
              + "".join(f"  {'alone at ' + format(t, '.0%'):>21}" for t in TARGETS))
        for m, e in stats["methods"].items():
            t = e["tasks"][task]
            lo, hi = t["accuracy_ci"]
            raw = t["at_0.9_untuned"]

            def fmt(x):
                h = x["heldout"]
                acc = f"{h['accuracy']:.0%}" if h["accuracy"] is not None else "–"
                return f"{h['coverage']:>4.0%} at {acc:>4} (t {min(x['threshold'], 1):.2f})"
            print(f"  {e['label']:28} {t['accuracy']:6.1%} [{lo:.0%}–{hi:.0%}] {t['brier']:6.3f} {t['ece']:6.3f}  "
                  f"{raw['coverage']:>6.0%} at {(raw['accuracy'] or 0):>4.0%}    "
                  + "".join(f"  {fmt(t['targets'][str(x)]):>21}" for x in TARGETS))
    for m in ("jev", "strands"):
        e = stats["methods"].get(m)
        if e:
            cost = f", ${e['usd_per_10k']:.2f} per 10,000 complaints" if "usd_per_10k" in e else ""
            print(f"\n{e['label']} ({e['model']}): median {e['latency_ms_median'] / 1000:.2f} s per complaint, "
                  f"{e['tokens_per_complaint']} input tokens{cost}")
    for task, a in stats["agreement"].items():
        print(f"{task}: Jev and Strands agree on {a['agree_rate']:.0%}, and are right {a['accuracy_when_agree']:.0%} "
              f"of those times; when they differ Jev is right {a['jev_right_when_differ']:.0%}, "
              f"Strands {a['strands_right_when_differ']:.0%}; all three of Jev, Strands and the 21,739-label "
              f"classifier give the same other answer for {a['all_three_overrule_label']} complaints")
