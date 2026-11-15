"""autolabel build-data -> labeled splits from the public complaint database
autolabel run        -> ask a backend (jev or strands) about every complaint in a split
autolabel compare    -> held-out comparison of every backend and two classifiers, with an HTML report
autolabel label      -> label your own complaints, keeping only labels the model is sure of"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .deciders import BACKENDS, Decider
from .questions import PRODUCTS, questions, state, taxonomy
from .run import RESULTS, run_sync


def cmd_compare(_a) -> None:
    from .compare import compare, print_table
    from .report import render

    stats = compare()
    print_table(stats)
    path = RESULTS / "compare" / "report.html"
    path.write_text(render(stats))
    print(f"\nwrote {path}")


def threshold_for(backend: str, task: str, target: str) -> float:
    stats_path = RESULTS / "compare" / "stats.json"
    if not stats_path.exists():
        raise SystemExit("run `autolabel compare` first, or pass --min-confidence")
    return json.loads(stats_path.read_text())["methods"][backend]["tasks"][task]["targets"][target]["threshold"]


async def label(a) -> None:
    lines = [line for line in (sys.stdin if a.input == "-" else open(a.input)) if line.strip()]
    texts = [json.loads(line)["text"] if line.lstrip().startswith("{") else line.strip() for line in lines]
    t_product = a.min_confidence or threshold_for(a.backend, "product", a.target)
    t_issue = a.min_confidence or threshold_for(a.backend, "issue", a.target)
    issues, decider = taxonomy(), Decider(a.backend, a.concurrency)

    async def one(text: str) -> dict:
        # Product first; the issue question then offers the issues of the product it picked.
        describe = decider.backend.describe_options
        first = await decider.ask(state(text), {"product": questions(next(iter(PRODUCTS)), issues, describe)["product"]})
        product = first["answers"]["product"]
        second = await decider.ask(state(text), {"issue": questions(product["choice"], issues, describe)["issue"]})
        issue = second["answers"]["issue"]
        p_conf, i_conf = max(product["probabilities"].values()), max(issue["probabilities"].values())
        return {"text": text, "product": product["choice"], "product_confidence": p_conf,
                "issue": issue["choice"], "issue_confidence": i_conf,
                "auto": p_conf >= t_product and i_conf >= t_issue}

    try:
        out = await asyncio.gather(*(one(t) for t in texts))
    finally:
        await decider.close()
    for r in out:
        print(json.dumps(r, ensure_ascii=False) if a.json else
              f"{'AUTO  ' if r['auto'] else 'REVIEW'} {r['product']} ({r['product_confidence']:.2f}) · "
              f"{r['issue']} ({r['issue_confidence']:.2f}) · {r['text'][:70]!r}")
    if not a.json:
        def show(t: float) -> str:
            return f"≥ {t:.2f}" if t <= 1 else f"never: no threshold reached {a.target} accuracy on tune"
        print(f"\n{sum(r['auto'] for r in out)} of {len(out)} labeled automatically "
              f"(product {show(t_product)}; issue {show(t_issue)}); the rest need a person")


def main() -> None:
    p = argparse.ArgumentParser(prog="autolabel")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-data", help="build dev/tune/held-out splits from the public complaint database")
    b.add_argument("--parquet", type=Path, help="folder with the database's Parquet files (default: download them)")

    r = sub.add_parser("run", help="ask a backend about every complaint in a split (resumes if interrupted)")
    r.add_argument("split", choices=["dev", "tune", "heldout"])
    r.add_argument("--backend", choices=list(BACKENDS), required=True)
    r.add_argument("--concurrency", type=int, default=8)
    r.add_argument("--limit", type=int, help="only the first N complaints")

    sub.add_parser("compare", help="compare everything on held-out and write results/compare/report.html")

    lab = sub.add_parser("label", help="label complaints: one per line, or JSONL with a text field")
    lab.add_argument("input", help="file, or - for stdin")
    lab.add_argument("--backend", choices=list(BACKENDS), default="jev")
    lab.add_argument("--target", choices=["0.85", "0.9", "0.95"], default="0.9",
                     help="use the thresholds `compare` set for this accuracy on the tune split")
    lab.add_argument("--min-confidence", type=float, help="use this threshold instead")
    lab.add_argument("--concurrency", type=int, default=8)
    lab.add_argument("--json", action="store_true")

    a = p.parse_args()
    if a.cmd == "build-data":
        from .data import build
        build(a.parquet)
    elif a.cmd == "run":
        run_sync(a.backend, a.split, a.concurrency, a.limit)
    elif a.cmd == "compare":
        cmd_compare(a)
    else:
        asyncio.run(label(a))


if __name__ == "__main__":
    main()
