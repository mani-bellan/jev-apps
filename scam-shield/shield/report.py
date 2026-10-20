"""Self-contained HTML report for one eval run: the numbers, then every mistake next to Jev's answers."""

from html import escape

from .evaluate import fmt

CSS = """
body{font:14px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1f2328}
h1{font-size:1.5rem;margin-bottom:.2rem}h2{margin-top:2rem;font-size:1.15rem}.meta{color:#666}
table{border-collapse:collapse;width:100%;margin:.5rem 0}th,td{border-bottom:1px solid #e5e5e5;padding:.35rem .5rem;
text-align:left;vertical-align:top}th{background:#f6f8fa}td.num{text-align:right;font-variant-numeric:tabular-nums}
.msg{white-space:pre-wrap;max-width:520px}.tag{display:inline-block;border-radius:4px;padding:0 .4rem;font-weight:600}
.scam{background:#ffebe9;color:#cf222e}.safe{background:#dafbe1;color:#116329}.unsure{background:#fff8c5;color:#7d4e00}
.small{color:#666;font-size:12px}
"""

SECTIONS = [
    ("missed", "Missed scams (called safe)", lambda r: r["label"] == "scam" and r["verdict"] == "safe"),
    ("false-alarms", "False alarms (genuine messages called scam)", lambda r: r["label"] == "legit" and r["verdict"] == "scam"),
    ("unsure", "Still unsure", lambda r: r["verdict"] == "unsure"),
    ("investigated", "Investigated (the quick check was unsure and the message has links)",
     lambda r: bool(r.get("investigation"))),
    ("wrong-type", "Caught, but wrong scam type",
     lambda r: r.get("scam_type") and r["label"] == "scam" and r["jev"]["scam_type"] != r["scam_type"]),
]


def _summary(stats: dict) -> str:
    head = ("<tr><th>Method</th><th>Language</th><th>n</th><th>Catch rate</th><th>Missed</th><th>False alarms</th>"
            "<th>Spam flagged</th><th>Unsure</th><th>Type accuracy</th></tr>")
    rows = []
    for method, by_lang in stats["by_method"].items():
        for lang, m in by_lang.items():
            cells = [m["n"], fmt(m["catch_rate"]), fmt(m["missed"]), fmt(m["false_alarms"]), fmt(m["spam_flagged"]),
                     fmt(m["unsure"]), fmt(m["type_accuracy"])]
            rows.append(f"<tr><td>{method}</td><td>{lang}</td>" + "".join(f'<td class="num">{c}</td>' for c in cells) + "</tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def _row(r: dict) -> str:
    j = r["jev"]
    sender = f'<div class="small">from {escape(r["sender"])}</div>' if r.get("sender") else ""
    expected = r["label"] + (f' · {r["scam_type"]}' if r.get("scam_type") else "")
    inv = ""
    if r.get("investigation"):
        inv = f'<div class="small"><b>Investigated:</b> P(scam) {j["p_quick"]:.2f} → {j["p_scam"]:.2f}<br>' + "<br>".join(
            escape(f'{e["lands_on"]}: {e["domain_owner"]}; registered {e["domain_registered"]}; {e["fetch"]}')
            for e in r["investigation"]) + "</div>"
    return (f'<tr><td class="msg">{escape(r["text"])}{sender}<div class="small">{escape(r["id"])} · {r["lang"]}</div></td>'
            f"<td>{expected}</td>"
            f'<td><span class="tag {j["verdict"]}">{j["verdict"]}</span> P(scam) {j["p_scam"]:.2f}<br>'
            f'{j["scam_type"]} · {j["asks_for"]} · pressure {j["pressure"]:.1f} · {j["brand"]}'
            f'<div class="small">{escape(j["why"])}</div>{inv}</td></tr>')


def render(rows: list[dict], stats: dict, meta: dict) -> str:
    parts = [f"<h1>Scam Shield eval: {escape(meta['dataset'])}</h1>",
             f'<p class="meta">{meta["n"]} messages · {meta["model"]} · thresholds scam ≥ {meta["scam_at"]}, '
             f'safe ≤ {meta["safe_at"]} · ${stats["jev"]["cost_usd"]:.4f} of Jev · '
             f'{stats["jev"]["tokens_per_message"]} tokens and {stats["jev"]["median_latency_ms"]} ms median per message · '
             f'{escape(meta["started"])}</p>',
             "<h2>Summary</h2>", _summary(stats),
             '<p class="small">Catch rate: share of scams warned about. False alarms: share of genuine messages called a '
             "scam. Unsure messages count as neither. Baselines never answer unsure.</p>"]
    for anchor, title, pick in SECTIONS:
        picked = [r for r in rows if pick(r)]
        parts.append(f'<h2 id="{anchor}">{title}: {len(picked)}</h2>')
        if picked:
            parts.append("<table><tr><th>Message</th><th>Label</th><th>Jev</th></tr>"
                         + "".join(_row(r) for r in picked[:300]) + "</table>")
    return f"<!doctype html><meta charset=utf-8><title>Scam Shield eval</title><style>{CSS}</style>{''.join(parts)}"
