"""Renders the EKG report as one self-contained HTML file (inline SVG, no JS deps)."""

import html
import json

from .analysis import curve, derail_point, kill_step

OK, BAD, GRID, MUTED, BREAKER = "#22c55e", "#f43f5e", "#1f2a37", "#8b98a9", "#38bdf8"
LABEL_COLORS = {"progress": OK, "neutral": "#94a3b8", "mistake": "#f59e0b", "harmful": BAD}
HEADLINE_STEP = 3


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _axes(w, h, pad, xs: list[str], y_label: str, threshold: float | None) -> list[str]:
    l, r, t, b = pad
    out = []
    for v in (0, 0.25, 0.5, 0.75, 1):
        y = t + (1 - v) * (h - t - b)
        out.append(f'<line x1="{l}" x2="{w - r}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>')
        out.append(f'<text x="{l - 8}" y="{y + 4:.1f}" text-anchor="end" class="tick">{v:g}</text>')
    n = len(xs)
    for i, lab in enumerate(xs):
        x = l + (i / max(n - 1, 1)) * (w - l - r)
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{t}" y2="{h - b}" stroke="{GRID}"/>')
        out.append(f'<text x="{x:.1f}" y="{h - b + 18}" text-anchor="middle" class="tick">{_esc(lab)}</text>')
    out.append(f'<text x="14" y="{(h - b + t) / 2}" class="axis" transform="rotate(-90 14 {(h - b + t) / 2})" '
               f'text-anchor="middle">{_esc(y_label)}</text>')
    if threshold is not None:
        y = t + (1 - threshold) * (h - t - b)
        out.append(f'<line x1="{l}" x2="{w - r}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eab308" '
                   f'stroke-dasharray="6 5" stroke-width="1.5"/>')
        out.append(f'<text x="{w - r}" y="{y - 6:.1f}" text-anchor="end" class="thr">stop below {threshold:g}</text>')
    return out


def overlay_chart(runs, threshold, w=980, h=360) -> str:
    pad = (56, 24, 18, 40)
    l, r, t, b = pad
    n = max(len(curve(x)) for x in runs)
    xs = [str(i + 1) for i in range(n)]
    out = _axes(w, h, pad, xs, "P(on track)", threshold)

    def pt(i, p):
        return l + (i / max(n - 1, 1)) * (w - l - r), t + (1 - p) * (h - t - b)

    for run in sorted(runs, key=lambda x: x["success"]):  # draw successes on top
        c = curve(run)
        color = OK if run["success"] else BAD
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pt(i, p) for i, p in enumerate(c)))
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-opacity="0.45" '
                   f'stroke-linejoin="round"><title>{_esc(run["task_id"])} #{run["repeat"]}</title></path>')
        x, y = pt(len(c) - 1, c[-1])
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}" fill-opacity="0.8"/>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart">{"".join(out)}</svg>'


def by_step_chart(by_step, w=480, h=260) -> str:
    pad = (56, 20, 18, 40)
    l, r, t, b = pad
    xs = [str(s["step"]) for s in by_step]
    out = _axes(w, h, pad, xs, "share of runs", None)
    n = len(by_step)
    for key, color, name in (("caught_rate", BAD, "failing runs flagged"),
                             ("false_alarm_rate", OK, "passing runs flagged (false alarm)")):
        pts = [(l + (i / max(n - 1, 1)) * (w - l - r), t + (1 - s[key]) * (h - t - b)) for i, s in enumerate(by_step)]
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for (x, y), s in zip(pts, by_step):
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"><title>{name} by step '
                       f'{s["step"]}: {_pct(s[key])}</title></circle>')
    return f'<svg viewBox="0 0 {w} {h}" class="chart">{"".join(out)}</svg>'


def mini_chart(run, threshold, w=300, h=96) -> str:
    l, r, t, b = 8, 8, 10, 10
    c = curve(run)
    n = len(c)
    pts = [(l + (i / max(n - 1, 1)) * (w - l - r), t + (1 - p) * (h - t - b)) for i, p in enumerate(c)]
    color = OK if run["success"] else BAD
    ty = t + (1 - threshold) * (h - t - b)
    out = [f'<line x1="{l}" x2="{w - r}" y1="{ty:.1f}" y2="{ty:.1f}" stroke="#eab308" stroke-opacity="0.5" '
           f'stroke-dasharray="4 4"/>']
    d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>')
    k = kill_step(run, threshold)
    if k is not None:
        x, y = pts[k]
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{t}" y2="{h - b}" stroke="#eab308" stroke-width="1.5"/>')
    for i, ((x, y), s) in enumerate(zip(pts, run["scores"])):
        label = "final answer" if i == len(run["steps"]) else run["steps"][i]["tool"]
        if i < len(run["steps"]) and run["steps"][i].get("blocked"):
            label += " (blocked by breaker)"
            out.append(f'<rect x="{x - 7:.1f}" y="{y - 7:.1f}" width="14" height="14" fill="none" '
                       f'stroke="{BREAKER}" stroke-width="2"/>')
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{5 if i == n - 1 else 4}" '
                   f'fill="{LABEL_COLORS.get(s["last_step"], MUTED)}" stroke="#0b0f14" stroke-width="1.5">'
                   f'<title>{i + 1}. {_esc(label)}: {s["last_step"]}, P(on track)={s["on_track"]:.2f}</title></circle>')
    return f'<svg viewBox="0 0 {w} {h}" class="mini">{"".join(out)}</svg>'


def run_card(run, threshold) -> str:
    k = kill_step(run, threshold)
    c = curve(run)
    status = ('<span class="ok">✓ passed</span>' if run["success"] else '<span class="bad">✗ failed</span>')
    blocked = sum(bool(st.get("blocked")) for st in run["steps"])
    if blocked:
        note = f"breaker blocked {blocked} call{'s' if blocked > 1 else ''}"
    elif k is not None:
        note = f"monitor stops it after step {k + 1}"
    elif c[-1] < 0.5:
        note = "flatlines at the final answer"
    elif derail_point(run) is not None:
        note = "dips, then recovers"
    else:
        note = "steady heartbeat"
    rows = []
    for i, (st, sc) in enumerate(zip(run["steps"], run["scores"])):
        gate = ""
        if "breaker_p" in st:
            gate = (f'<span class="blk">⛔ blocked, allow={st["breaker_p"]:.2f}</span> ' if st.get("blocked")
                    else f'<span class="p">gate allow={st["breaker_p"]:.2f}</span> ')
        rows.append(f'<li><b style="color:{LABEL_COLORS.get(sc["last_step"], MUTED)}">{sc["last_step"]}</b> {gate}'
                    f'<code>{_esc(st["tool"])}({_esc(json.dumps(st["args"]))[:140]})</code> '
                    f'<span class="p">{sc["on_track"]:.2f}</span></li>')
    fs = run["scores"][-1]
    rows.append(f'<li><b style="color:{LABEL_COLORS.get(fs["last_step"], MUTED)}">{fs["last_step"]}</b> '
                f'answer: “{_esc(run["answer"][:200])}” <span class="p">{fs["on_track"]:.2f}</span></li>')
    tier = '<span class="hard">hard</span>' if run.get("tier") == "hard" else ""
    return (f'<div class="card"><div class="card-h"><span class="tid">{_esc(run["task_id"])} '
            f'<span class="rep">#{run["repeat"]}</span>{tier}</span>{status}</div>{mini_chart(run, threshold)}'
            f'<div class="note">{note}</div><details><summary>steps</summary><ol>{"".join(rows)}</ol>'
            f'</details></div>')


def render(runs: list[dict], stats: dict, meta: dict) -> str:
    best = stats["best"]
    thr = best["threshold"]
    head = next((s for s in stats["by_step"] if s["step"] == HEADLINE_STEP), stats["by_step"][-1])
    tiers = {}
    for run in runs:
        t = tiers.setdefault(run.get("tier", "easy"), [0, 0])
        t[0] += run["success"]
        t[1] += 1
    tier_text = " · ".join(f"{k} {p}/{n}" for k, (p, n) in sorted(tiers.items()))
    cards = [
        ("Runs passed", f'{stats["passed"]}/{stats["runs"]}', tier_text if len(tiers) > 1 else
         f'{stats["failed"]} failed'),
        (f'Failing runs flagged by step {head["step"]}', _pct(head["caught_rate"]),
         f'{_pct(head["false_alarm_rate"])} false alarms on passing runs'),
        ("Agent tokens saved by stopping early", _pct(best["tokens_saved_rate"]),
         f'stop when P(on track) &lt; {thr:g} · {best["false_kills"]} good runs stopped'),
        ("Jev cost to score every step", f'${stats["jev_cost_usd"]:.4f}', f'{stats["jev_calls"]} Jev calls'),
    ]
    card_html = "".join(f'<div class="stat"><div class="sl">{a}</div><div class="sv">{b}</div>'
                        f'<div class="ss">{c}</div></div>' for a, b, c in cards)
    stop_rows = "".join(
        f'<tr class="{"sel" if s["threshold"] == thr else ""}"><td>{s["threshold"]:g}</td>'
        f'<td>{_pct(s["caught_rate"])} ({s["caught"]})</td><td>{_pct(s["false_kill_rate"])} ({s["false_kills"]})</td>'
        f'<td>{_pct(s["wasted_tokens_saved_rate"])}</td><td>{_pct(s["tokens_saved_rate"])}</td></tr>'
        for s in stats["stops"])
    auc_rows = "".join(f'<td>{s["auc"]:.2f}</td>' if s["auc"] is not None else "<td>–</td>" for s in stats["by_step"])
    ordered = sorted(runs, key=lambda r: (r["success"], r["task_id"], r["repeat"]))
    breaker_html = ""
    if stats.get("breaker"):
        b = stats["breaker"]
        blocked_rows = "".join(
            f'<tr><td>{_esc(r["task_id"])} #{r["repeat"]}</td><td><code>{_esc(st["tool"])}'
            f'({_esc(json.dumps(st["args"]))[:110]})</code></td><td>{st["breaker_p"]:.2f}</td>'
            f'<td>{"<span class=ok>passed</span>" if r["success"] else "<span class=bad>failed</span>"}</td></tr>'
            for r in ordered for st in r["steps"] if st.get("blocked"))
        breaker_html = f"""<h2>Circuit breaker</h2>
<p class="lead">Before any tool call that changes the world, Jev was asked whether it should run. Calls below
{meta.get("breaker")} were blocked and the agent was told to verify or ask the user.
<b>{b["blocked"]}</b> of <b>{b["gated"]}</b> gated calls blocked · median check {b["median_ms"]} ms.</p>
<div class="panel"><table><tr><th>run</th><th>blocked call</th><th>allow</th><th>run outcome</th></tr>
{blocked_rows or '<tr><td colspan="4">nothing blocked</td></tr>'}</table></div>"""
    legend = "".join(f'<span><i style="background:{c}"></i>{k}</span>' for k, c in LABEL_COLORS.items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Agent EKG</title>
<style>
body{{margin:0;background:#0b0f14;color:#e5ecf4;font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:36px 28px 60px}}
h1{{font-size:34px;margin:0;letter-spacing:-.02em}} h1 span{{color:{OK}}}
h2{{font-size:18px;margin:40px 0 6px}} .sub{{color:{MUTED};margin:4px 0 26px}} .lead{{color:{MUTED};margin:0 0 14px;max-width:760px}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.stat{{background:#111823;border:1px solid {GRID};border-radius:10px;padding:14px 16px}}
.sl{{color:{MUTED};font-size:12.5px}} .sv{{font-size:30px;font-weight:700;margin:2px 0}} .ss{{color:{MUTED};font-size:12.5px}}
.panel{{background:#0e141c;border:1px solid {GRID};border-radius:12px;padding:14px}}
.chart{{width:100%;height:auto;display:block}} .tick{{fill:{MUTED};font-size:12px}} .axis{{fill:{MUTED};font-size:12px}}
.thr{{fill:#eab308;font-size:12px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}} th,td{{padding:7px 8px;border-bottom:1px solid {GRID};text-align:left}}
th{{color:{MUTED};font-weight:500}} tr.sel td{{background:#1a2230;color:#fde68a}}
.legend{{display:flex;gap:16px;color:{MUTED};font-size:13px;margin:6px 0 12px}} .legend i{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.card{{background:#111823;border:1px solid {GRID};border-radius:10px;padding:10px 12px}}
.card-h{{display:flex;justify-content:space-between;font-size:13.5px}} .tid{{font-weight:600}} .rep{{color:{MUTED};font-weight:400}}
.hard{{margin-left:6px;font-size:11px;padding:1px 6px;border-radius:6px;background:#3b2a12;color:#fbbf24;font-weight:500}}
.blk{{color:{BREAKER};font-weight:600}}
.ok{{color:{OK}}} .bad{{color:{BAD}}} .mini{{width:100%;height:auto;display:block;margin:4px 0}}
.note{{color:{MUTED};font-size:12.5px}} details{{font-size:12.5px;margin-top:4px}} summary{{cursor:pointer;color:{MUTED}}}
ol{{padding-left:18px;margin:6px 0}} li{{margin:3px 0}} code{{color:#cbd5e1;font-size:11.5px;word-break:break-all}} .p{{color:{MUTED}}}
.foot{{color:{MUTED};font-size:12.5px;margin-top:36px}}
</style></head><body><main>
<h1>Agent <span>EKG</span></h1>
<div class="sub">Every step of every agent run scored live by Jev · agent: {_esc(meta["agent"])} · {_esc(meta["created"])}</div>
<div class="stats">{card_html}</div>

<h2>Heartbeats</h2>
<p class="lead">After each tool call, Jev reads the run so far and answers one question: is this agent still on track?
<span class="ok">Green</span> runs passed the task's checker, <span class="bad">red</span> runs failed. Jev never sees the checker.</p>
<div class="panel">{overlay_chart(runs, thr)}</div>

{breaker_html}

<div class="two">
<div><h2>How early can we tell?</h2>
<p class="lead">Share of runs flagged (P(on track) &lt; {thr:g}) within the first N tool steps.</p>
<div class="panel">{by_step_chart(stats["by_step"])}</div></div>
<div><h2>Stopping doomed runs</h2>
<p class="lead">Replay of every run with a monitor that stops it at the first step below the threshold.</p>
<div class="panel"><table><tr><th>stop below</th><th>failures caught</th><th>good runs stopped</th>
<th>failed-run tokens saved</th><th>all tokens saved</th></tr>{stop_rows}</table></div></div>
</div>

<h2>Separating pass from fail</h2>
<p class="lead">AUC of 1 − P(on track) as a failure predictor after N steps (0.5 = coin flip, 1.0 = perfect).
At the final answer: <b>{stats["final_auc"] if stats["final_auc"] is None else f'{stats["final_auc"]:.2f}'}</b>.</p>
<div class="panel"><table><tr><th>after step</th>{"".join(f'<th>{s["step"]}</th>' for s in stats["by_step"])}</tr>
<tr><td>AUC</td>{auc_rows}</tr></table></div>

<h2>Every run</h2>
<div class="legend">Jev's label for each step: {legend}<span>· yellow line = monitor stops here</span><span><i style="background:none;border:2px solid {BREAKER};border-radius:0"></i>blocked by breaker</span></div>
<div class="grid">{"".join(run_card(r, thr) for r in ordered)}</div>
<div class="foot">Generated by agent-ekg. Pass/fail comes from deterministic checks on the final world state.
Jev: TypeSafe System One model, ${0.042}/1M input tokens.</div>
</main></body></html>"""
