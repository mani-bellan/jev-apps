"""One self-contained HTML page with the comparison: summary tables and inline SVG charts."""

import html

COLORS = {"jev": "#38bdf8", "strands": "#f59e0b", "tfidf-21k": "#a3aab5", "tfidf-440": "#6b7280"}
DASH = {"tfidf-440": "5 4"}
TASK_TITLE = {"product": "Product (11 options)", "issue": "Issue (3 to 10 options, true product given)"}

CSS = """
body{margin:0;background:#0b0e13;color:#d6dbe3;font:15px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}
main{max-width:64rem;margin:0 auto;padding:2rem 1.25rem 5rem}
h1{font-size:1.7rem;margin:.2rem 0 .4rem}h2{font-size:1.2rem;margin:2.2rem 0 .6rem}
.muted{color:#8b95a5}table{border-collapse:collapse;width:100%;margin:.6rem 0 1rem;font-size:.9rem}
th,td{padding:.4rem .55rem;border-bottom:1px solid #232a35;text-align:right}th{background:#131922}
td:first-child,th:first-child{text-align:left}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(28rem,1fr));gap:1.25rem}
figure{margin:0;padding:1rem 1rem .6rem;border:1px solid #232a35;border-radius:12px;background:#0f141b}
figcaption{font-size:.85rem;color:#8b95a5;margin-top:.3rem}
.legend{display:flex;flex-wrap:wrap;gap:.4rem 1rem;font-size:.85rem;margin:.2rem 0 .4rem}
.legend span{display:inline-flex;align-items:center;gap:.35rem}.sw{width:18px;height:3px;border-radius:2px}
"""


def _esc(s) -> str:
    return html.escape(str(s))


def _pct(x, digits=0) -> str:
    return "–" if x is None else f"{x * 100:.{digits}f}%"


def _swatch(m) -> str:
    c = COLORS[m]
    return f"repeating-linear-gradient(90deg,{c} 0 5px,transparent 5px 9px)" if m in DASH else c


def _legend(methods) -> str:
    return '<div class="legend">' + "".join(
        f'<span><i class="sw" style="background:{_swatch(m)}"></i>{_esc(e["label"])}</span>'
        for m, e in methods.items()) + "</div>"


def _axes(w, h, pad, x_ticks, y_ticks, x_label, y_label, y0, y1) -> str:
    l, r, t, b = pad
    out = []
    for v in y_ticks:
        y = t + (1 - (v - y0) / (y1 - y0)) * (h - t - b)
        out.append(f'<line x1="{l}" x2="{w - r}" y1="{y:.1f}" y2="{y:.1f}" stroke="#1f2630"/>'
                   f'<text x="{l - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="#8b95a5">{v:.0%}</text>')
    for v in x_ticks:
        x = l + v * (w - l - r)
        out.append(f'<text x="{x:.1f}" y="{h - b + 18}" text-anchor="middle" font-size="12" fill="#8b95a5">{v:.0%}</text>')
    out.append(f'<text x="{(l + w - r) / 2}" y="{h - 6}" text-anchor="middle" font-size="12.5" fill="#c9d1d9">{x_label}</text>')
    out.append(f'<text transform="translate(14 {(t + h - b) / 2}) rotate(-90)" text-anchor="middle" font-size="12.5" '
               f'fill="#c9d1d9">{y_label}</text>')
    out.append(f'<rect x="{l}" y="{t}" width="{w - l - r}" height="{h - t - b}" fill="none" stroke="#2c3542"/>')
    return "".join(out)


def coverage_chart(stats, task) -> str:
    w, h, pad = 560, 340, (56, 16, 14, 46)
    l, r, t, b = pad
    y0, y1 = 0.5, 1.0

    def xy(cov, acc):
        return l + cov * (w - l - r), t + (1 - (max(acc, y0) - y0) / (y1 - y0)) * (h - t - b)
    parts = [_axes(w, h, pad, [0, .25, .5, .75, 1], [.5, .6, .7, .8, .9, 1.0],
                   "Share of complaints it labels on its own (most confident first)", "Accuracy of those labels", y0, y1)]
    yy = xy(0, 0.95)[1]
    parts.append(f'<line x1="{l}" x2="{w - r}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="#f43f5e" stroke-dasharray="3 3"/>'
                 f'<text x="{w - r - 4}" y="{yy - 5:.1f}" text-anchor="end" font-size="11.5" fill="#f43f5e">95% accurate</text>')
    for m, e in stats["methods"].items():
        pts = [(0, e["tasks"][task]["curve"][0][1])] + e["tasks"][task]["curve"]
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(xy(c, a) for c, a in pts))
        parts.append(f'<path d="{d}" fill="none" stroke="{COLORS[m]}" stroke-width="2.4" '
                     f'stroke-dasharray="{DASH.get(m, "")}"/>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">{"".join(parts)}</svg>'


def reliability_chart(stats, task) -> str:
    w, h, pad = 560, 340, (56, 16, 14, 46)
    l, r, t, b = pad

    def xy(c, a):
        return l + c * (w - l - r), t + (1 - a) * (h - t - b)
    parts = [_axes(w, h, pad, [0, .2, .4, .6, .8, 1], [0, .2, .4, .6, .8, 1.0],
                   "How sure the model said it was (confidence)", "How often it was right", 0, 1)]
    (x0, y0_), (x1, y1_) = xy(0, 0), xy(1, 1)
    parts.append(f'<line x1="{x0}" y1="{y0_}" x2="{x1}" y2="{y1_}" stroke="#4b5563" stroke-dasharray="4 4"/>'
                 f'<text x="{xy(.12, .19)[0]:.1f}" y="{xy(.12, .19)[1]:.1f}" font-size="11.5" fill="#6b7686" '
                 f'transform="rotate(-31 {xy(.12, .19)[0]:.1f} {xy(.12, .19)[1]:.1f})">perfectly calibrated</text>')
    total = {m: sum(bk["n"] for bk in stats["methods"][m]["tasks"][task]["reliability"]) for m in ("jev", "strands")
             if m in stats["methods"]}
    for m in total:
        bins = [bk for bk in stats["methods"][m]["tasks"][task]["reliability"] if bk["n"] >= 5]
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
                     for i, (x, y) in enumerate(xy(bk["confidence"], bk["accuracy"]) for bk in bins))
        parts.append(f'<path d="{d}" fill="none" stroke="{COLORS[m]}" stroke-width="2"/>')
        for bk in bins:
            x, y = xy(bk["confidence"], bk["accuracy"])
            rad = 3 + 9 * (bk["n"] / total[m]) ** 0.5
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" fill="{COLORS[m]}" fill-opacity=".35" '
                         f'stroke="{COLORS[m]}"><title>{bk["n"]} complaints</title></circle>')
    # Name each model's biggest bin, where most of its answers sit, in the empty lower right, with a leader line.
    for k, m in enumerate(total):
        bins = stats["methods"][m]["tasks"][task]["reliability"]
        top = max(bins, key=lambda bk: bk["n"])
        x, y = xy(top["confidence"], top["accuracy"])
        tx, ty = xy(0.97, 0.2 - 0.09 * k)
        parts.append(f'<line x1="{tx + 4:.1f}" y1="{ty - 4:.1f}" x2="{x:.1f}" y2="{y + 6:.1f}" stroke="{COLORS[m]}" '
                     f'stroke-width="1" stroke-dasharray="2 3"/>'
                     f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="end" font-size="12" fill="{COLORS[m]}">'
                     f'{top["n"]} answers: {top["confidence"]:.0%} sure, right {top["accuracy"]:.0%}'
                     f'</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img">{"".join(parts)}</svg>'


def summary_table(stats, task) -> str:
    rows = []
    for m, e in stats["methods"].items():
        t = e["tasks"][task]
        lo, hi = t["accuracy_ci"]
        cells = [f"<td>{_esc(e['label'])}</td>", f"<td>{_pct(t['accuracy'], 1)} <span class=muted>({lo:.0%}–{hi:.0%})</span></td>",
                 f"<td>{t['ece']:.3f}</td>", f"<td>{t['brier']:.3f}</td>",
                 f"<td>{_pct(t['at_0.9_untuned']['coverage'])} at {_pct(t['at_0.9_untuned']['accuracy'])}</td>"]
        for target in map(str, stats["meta"]["targets"]):
            x = t["targets"][target]
            hh = x["heldout"]
            cells.append(f"<td>{_pct(hh['coverage'])} at {_pct(hh['accuracy'])} "
                         f"<span class=muted>(≥ {min(x['threshold'], 1):.2f})</span></td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return ("<table><tr><th>Method</th><th>Accuracy (95% interval)</th><th>Calibration error</th><th>Brier</th>"
            "<th>Confidence ≥ 0.9, as is</th>" + "".join(f"<th>Labels alone, aiming at {t:.0%}</th>" for t in stats["meta"]["targets"])
            + "</tr>"
            + "".join(rows) + "</table>")


def render(stats: dict) -> str:
    meta, methods = stats["meta"], stats["methods"]
    body = [f"<h1>Autolabel: Jev vs Strands Decider</h1><p class=muted>{meta['heldout']} held-out consumer complaints, "
            f"{meta['products']} products, {meta['issues']} issues. Thresholds set on {meta['tune']} tune complaints, "
            "per method, then applied unchanged.</p>"]
    for task in ("product", "issue"):
        body.append(f"<h2>{TASK_TITLE[task]}</h2>{summary_table(stats, task)}")
        body.append(f'<div class="charts"><figure id="coverage-{task}">{_legend(methods)}{coverage_chart(stats, task)}'
                    f'<figcaption>How much each method can label on its own, and how accurate those labels are. '
                    f'Further right at the same height is better. A flat stretch is a block of complaints given the same confidence.</figcaption></figure>'
                    f'<figure id="reliability-{task}">{_legend({m: methods[m] for m in ("jev", "strands") if m in methods})}'
                    f'{reliability_chart(stats, task)}<figcaption>Calibration on held-out: each dot is a confidence bin '
                    f'(bigger dot, more complaints; bins under 5 complaints not drawn). On the diagonal, "90% sure" means right 90% of the time.'
                    f'</figcaption></figure></div>')
    cost = []
    for m in ("jev", "strands"):
        if m in methods:
            e = methods[m]
            cost.append(f"<tr><td>{_esc(e['label'])}</td><td>{_esc(e['model'])}</td>"
                        f"<td>{e['latency_ms_median'] / 1000:.2f} s</td><td>{e['tokens_per_complaint']}</td>"
                        f"<td>{'$%.2f' % e['usd_per_10k'] if 'usd_per_10k' in e else 'your hardware'}</td></tr>")
    body.append("<h2>Speed and cost</h2><table><tr><th>Backend</th><th>Model</th><th>Median per complaint</th>"
                "<th>Input tokens</th><th>Per 10,000 complaints</th></tr>" + "".join(cost) + "</table>")
    if stats["agreement"]:
        body.append("<h2>When the two models agree</h2><table><tr><th>Task</th><th>Agree</th><th>Right when they agree"
                    "</th><th>Jev right when they differ</th><th>Strands right when they differ</th>"
                    "<th>Jev, Strands and the 21,739-label classifier all overrule the label</th></tr>" + "".join(
                        f"<tr><td>{t}</td><td>{_pct(a['agree_rate'])}</td><td>{_pct(a['accuracy_when_agree'])}</td>"
                        f"<td>{_pct(a['jev_right_when_differ'])}</td><td>{_pct(a['strands_right_when_differ'])}</td>"
                        f"<td>{a['all_three_overrule_label']}</td></tr>"
                        for t, a in stats["agreement"].items()) + "</table>")
    products = list(next(iter(stats["per_product"].values())))
    body.append("<h2>Product accuracy by product</h2><table><tr><th>Product</th>"
                + "".join(f"<th>{_esc(methods[m]['label'])}</th>" for m in stats["per_product"]) + "</tr>" + "".join(
                    f"<tr><td>{_esc(p)}</td>" + "".join(f"<td>{_pct(stats['per_product'][m][p])}</td>"
                                                       for m in stats["per_product"]) + "</tr>" for p in products)
                + "</table>")
    for m in ("jev", "strands"):
        if m in stats["confusions"]:
            body.append(f"<h2>Most common product mistakes: {_esc(methods[m]['label'])}</h2><table><tr><th>True product"
                        "</th><th>Labeled as</th><th>Complaints</th></tr>" + "".join(
                            f"<tr><td>{_esc(c['gold'])}</td><td>{_esc(c['predicted'])}</td><td>{c['n']}</td></tr>"
                            for c in stats["confusions"][m]) + "</table>")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport "
            f"content='width=device-width,initial-scale=1'><title>Autolabel: Jev vs Strands Decider</title>"
            f"<style>{CSS}</style></head><body><main>{''.join(body)}</main></body></html>")
