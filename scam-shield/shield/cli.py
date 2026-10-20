"""shield check -> verdict for one message
shield eval  -> accuracy on a labeled set, with baselines and an HTML report
shield label -> build a labeled set from raw messages, masking private numbers first
shield serve -> demo web page"""

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

from . import baselines, policy
from .data import load
from .evaluate import print_table, summarize
from .extract import detect_lang, redact
from .investigate import Investigator
from .jev import DEFAULT_MODEL, SCAM_TYPES, Jev
from .pipeline import assess
from .report import render

COLORS = {"scam": "\033[1;31m", "unsure": "\033[1;33m", "safe": "\033[1;32m"}


def paint(verdict: str, text: str) -> str:
    return f"{COLORS[verdict]}{text}\033[0m" if sys.stdout.isatty() else text


def print_verdict(res: dict, d: dict) -> None:
    print(f"{paint(d['verdict'], d['verdict'].upper()):<7} ({d['p_scam']:.2f})  {d['scam_type']} · "
          f"{policy.ASKS[d['asks_for']]} · pressure {d['pressure']:.1f}/2 · claims to be {d['brand']}")
    print(f"Why:  {d['why']}")
    print(f"Do:   {d['do']}")
    print(f"      {res['model']} · {res['latency_ms']} ms of Jev · {res['input_tokens']} tokens"
          + (" · links investigated" if res.get("investigation") else ""))


def print_explain(res: dict) -> None:
    s = res["state"]
    print(f"\nJev saw:\n  sender: {s['sender']['id']} ({s['sender']['kind']})\n  links:  {s['link_domains'] or 'none'}")
    print("  message: " + s["message"].replace("\n", "\n           "))
    a = res["answers"]
    print(f"\nis_scam    P(yes) = {a['is_scam']['noul']:.3f}   (scam ≥ {policy.SCAM_AT}, safe ≤ {policy.SAFE_AT})")
    for q in ("scam_type", "asks_for", "brand"):
        top = sorted(a[q]["probabilities"].items(), key=lambda kv: -kv[1])[:3]
        print(f"{q:<10} {a[q]['choice']} (confidence {a[q]['confidence']:.2f})   "
              + ", ".join(f"{k} {v:.2f}" for k, v in top))
    probs = ", ".join(f"{k}: {v:.2f}" for k, v in a["pressure"]["probabilities"].items())
    print(f"pressure   {a['pressure']['score']:.2f} of 2 (confidence {a['pressure']['confidence']:.2f})   {probs}")


def print_investigation(res: dict) -> None:
    d = res["decision"]
    print(f"\nInvestigated: P(scam) {d['p_quick']:.2f} → {d['p_scam']:.2f}")
    for e in res["investigation"]:
        print(f"  {e['link']}")
        if "redirected_from" in e:
            print(f"    redirected from {e['redirected_from']}")
        print(f"    lands on {e['lands_on']}: {e['domain_owner']}")
        print(f"    registered {e['domain_registered']}")
        print(f"    {e['fetch']}" + (f": \"{e['page']['title']}\"" if e.get("page", {}).get("title") else ""))
        if e.get("page", {}).get("form_fields"):
            print(f"    form asks for: {', '.join(e['page']['form_fields'])}")


async def cmd_check(a) -> None:
    text = (sys.stdin.read() if a.text == "-" else a.text).strip()
    jev, inv = Jev(a.model), None if a.no_investigate else Investigator()
    try:
        res = await assess(jev, inv, text, a.sender, force=a.investigate)
    finally:
        await jev.close()
        if inv:
            await inv.close()
    d = res["decision"]
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return
    print_verdict(res, d)
    if res["investigation"]:
        print_investigation(res)
    if a.explain:
        print_explain(res)


async def cmd_eval(a) -> None:
    records = load(a.dataset, a.sample, a.seed)
    methods = ["jev"] + ([] if a.no_investigate else ["jev-quick"]) + [m for m in a.baseline.split(",") if m]
    print(f"{len(records)} messages from {a.dataset} → Jev {a.model}"
          + ("" if a.no_investigate else ", investigating unsure messages with links"))
    jev, inv = Jev(a.model, a.concurrency), None if a.no_investigate else Investigator()
    done = 0

    async def one(r):
        nonlocal done
        res = await assess(jev, inv, r["text"], r.get("sender"), as_of=received_on(r))
        done += 1
        if done % 50 == 0 or done == len(records):
            print(f"  {done}/{len(records)}")
        return res

    started = dt.datetime.now()
    try:
        results = await asyncio.gather(*(one(r) for r in records))
    finally:
        await jev.close()
        if inv:
            await inv.close()
    rows = []
    for r, res in zip(records, results):
        rows.append({**r, "verdict": res["decision"]["verdict"], "verdict_quick": res["quick"]["verdict"],
                     "jev": res["decision"], "answers": res["answers"], "investigation": res["investigation"],
                     "latency_ms": res["latency_ms"], "input_tokens": res["input_tokens"]})
    if "rules" in methods:
        for r in rows:
            r["baseline_rules"] = baselines.rules(r)
    if "tfidf" in methods:
        preds = baselines.tfidf(rows)
        if preds is None:
            print("  tfidf baseline skipped: needs at least 5 scams and 5 non-scams")
            methods.remove("tfidf")
        else:
            for r, p in zip(rows, preds):
                r["baseline_tfidf"] = p

    stats = summarize(rows, methods)
    meta = {"dataset": a.dataset, "n": len(rows), "model": a.model, "scam_at": policy.SCAM_AT,
            "safe_at": policy.SAFE_AT, "started": started.isoformat(timespec="seconds"),
            "seconds": round((dt.datetime.now() - started).total_seconds(), 1)}
    out = a.out or Path("results") / started.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    (out / "stats.json").write_text(json.dumps({"meta": meta, **stats}, indent=2))
    (out / "report.html").write_text(render(rows, stats, meta))

    j = stats["jev"]
    print(f"\n{len(rows)} messages · {meta['seconds']} s · ${j['cost_usd']:.4f} of Jev · "
          f"{j['tokens_per_message']} tokens/message · {j['median_latency_ms']} ms median")
    print_table(stats)
    print(f"\nwrote {out / 'report.html'}")


def received_on(record: dict) -> dt.date | None:
    """When the message was received, from a `published` date like 2025-11 or 2025-11-04, so domain age is
    measured at that time rather than today."""
    published = record.get("published") or ""
    try:
        return dt.date.fromisoformat(published if len(published) == 10 else published[:7] + "-01")
    except ValueError:
        return None


def read_raw(path: Path) -> list[dict]:
    """Messages separated by blank lines. An optional first line 'From: <sender>' sets the sender."""
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    messages = []
    for block in path.read_text().split("\n\n"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        sender = None
        if lines[0].lower().startswith(("from:", "sender:")):
            sender = lines.pop(0).split(":", 1)[1].strip()
        messages.append({"text": "\n".join(lines).strip(), "sender": sender})
    return messages


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


async def cmd_label(a) -> None:
    raw = read_raw(a.input)
    seen = set()
    if a.out.exists():
        seen = {json.loads(line)["text"] for line in a.out.read_text().splitlines() if line.strip()}
    todo = [m for m in raw if redact(m["text"]) not in seen]
    print(f"{len(raw)} messages in {a.input}, {len(raw) - len(todo)} already in {a.out}, {len(todo)} to label")
    print("Keys: Enter = accept suggestion · s = scam · l = legit · p = promotional spam · x = skip · q = quit\n")
    scam_types = [t for t in SCAM_TYPES if t not in ("genuine_transaction", "genuine_promotion", "personal", "unclear")]
    jev = None if a.no_suggest else Jev(a.model)
    saved = 0
    try:
        for i, m in enumerate(todo, 1):
            text, sender = redact(m["text"]), redact(m["sender"]) if m.get("sender") else None
            print(f"── {i}/{len(todo)} " + (f"from {sender} " if sender else "") + "─" * 40)
            print(text)
            suggestion, kind = None, None
            if jev:
                d = policy.decide((await jev.check(m["text"], m.get("sender")))["answers"])
                kind = d["scam_type"] if d["scam_type"] in scam_types else None
                suggestion = {"scam": "scam", "unsure": None}.get(
                    d["verdict"], "spam" if d["scam_type"] == "genuine_promotion" else "legit")
                print(f"  Jev: {d['verdict']} ({d['p_scam']:.2f}) · {d['scam_type']}")
            while True:
                key = ask(f"  label [{suggestion or 'no suggestion'}]: ")
                label = {"": suggestion, "s": "scam", "l": "legit", "p": "spam"}.get(key)
                if key in ("x", "q") or label:
                    break
            if key == "q":
                break
            if key == "x":
                continue
            record = {"text": text, "label": label, "lang": detect_lang(text), "source": a.source}
            if sender:
                record["sender"] = sender
            if label == "scam":
                menu = "  " + "  ".join(f"{n}={t}" for n, t in enumerate(scam_types, 1))
                print(menu)
                pick = ask(f"  scam type [{kind or 'skip'}]: ")
                if pick.isdigit() and 1 <= int(pick) <= len(scam_types):
                    kind = scam_types[int(pick) - 1]
                if kind:
                    record["scam_type"] = kind
            a.out.parent.mkdir(parents=True, exist_ok=True)
            with a.out.open("a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            saved += 1
    finally:
        if jev:
            await jev.close()
    print(f"\nsaved {saved} labeled messages to {a.out}")


def main() -> None:
    p = argparse.ArgumentParser(prog="shield")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="verdict for one message")
    c.add_argument("text", help="the message, or - to read it from stdin")
    c.add_argument("--sender", help="sender ID or number, e.g. VM-HDFCBK-S or +919876543210")
    c.add_argument("--explain", action="store_true", help="show what Jev saw and every answer")
    c.add_argument("--json", action="store_true", help="raw JSON output")
    c.add_argument("--investigate", action="store_true", help="check links even when the quick check is confident")
    c.add_argument("--no-investigate", action="store_true", help="quick check only")
    c.add_argument("--model", default=DEFAULT_MODEL)

    e = sub.add_parser("eval", help="accuracy on a labeled set")
    e.add_argument("dataset", help="a .jsonl file, or a public set: mendeley, hinglish-hf")
    e.add_argument("--sample", type=int, help="stratified sample of this many messages")
    e.add_argument("--seed", type=int, default=7)
    e.add_argument("--baseline", default="rules,tfidf", help="comma-separated: rules, tfidf (empty for none)")
    e.add_argument("--model", default=DEFAULT_MODEL)
    e.add_argument("--concurrency", type=int, default=8)
    e.add_argument("--no-investigate", action="store_true", help="quick check only")
    e.add_argument("--out", type=Path, help="output directory (default results/<timestamp>)")

    lab = sub.add_parser("label", help="label raw messages into a .jsonl set")
    lab.add_argument("input", type=Path, help="text file with messages separated by blank lines, or a .jsonl")
    lab.add_argument("--out", type=Path, required=True)
    lab.add_argument("--source", default="collected", help="where these messages came from, stored per record")
    lab.add_argument("--no-suggest", action="store_true", help="label blind, without Jev's suggestion")
    lab.add_argument("--model", default=DEFAULT_MODEL)

    sv = sub.add_parser("serve", help="demo web page: paste a message, see the verdict and evidence")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--model", default=DEFAULT_MODEL)

    a = p.parse_args()
    if a.cmd == "serve":
        from .web import serve
        return serve(a.port, a.model)
    asyncio.run({"check": cmd_check, "eval": cmd_eval, "label": cmd_label}[a.cmd](a))


if __name__ == "__main__":
    main()
