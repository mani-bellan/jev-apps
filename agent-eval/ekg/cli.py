"""ekg run     -> run the agent on every task, score each step with Jev, write the report
ekg report  -> re-render the report from a saved runs.json
ekg compare -> per-task pass rates of two results directories (e.g. without and with --breaker)"""

import argparse
import asyncio
import datetime as dt
import json
import random
from pathlib import Path

from .agents import OpenRouterAgent, ScriptedAgent
from .analysis import analyze
from .jev import Breaker, Jev
from .report import render
from .tasks import TASKS
from .world import new_world


def select_tasks(only: list[str] | None, tier: str):
    return [t for t in TASKS if (not only or t.id in only) and tier in ("all", t.tier)]


async def run_all(agent, jev: Jev, tasks, repeats: int, seed: int) -> list[dict]:

    async def one(task, rep):
        world = new_world()
        if task.setup:
            task.setup(world)
        try:
            traj = await agent.run(task, world, random.Random(f"{seed}-{task.id}-{rep}"))
        except RuntimeError as e:
            print(f"  ! {task.id} #{rep}: skipped ({e})")
            return None
        success = task.check(world, traj["answer"])
        scores = await jev.score(task.goal, traj)
        mark = "✓" if success else "✗"
        trace = " → ".join(f"{s['on_track']:.2f}" for s in scores)
        print(f"  {mark} {task.id} #{rep}: {len(traj['steps'])} steps, P(on track) {trace}")
        return {"task_id": task.id, "tier": task.tier, "goal": task.goal, "repeat": rep, "success": success, **traj, "scores": scores}

    runs = await asyncio.gather(*(one(t, r) for t in tasks for r in range(1, repeats + 1)))
    return [r for r in runs if r is not None]


def write_report(out: Path, runs: list[dict], meta: dict) -> dict:
    stats = analyze(runs)
    (out / "runs.json").write_text(json.dumps({"meta": meta, "runs": runs}, indent=2))
    (out / "stats.json").write_text(json.dumps(stats, indent=2))
    (out / "report.html").write_text(render(runs, stats, meta))
    return stats


def compare(dir_a: Path, dir_b: Path) -> None:
    sides = [json.loads((d / "runs.json").read_text()) for d in (dir_a, dir_b)]
    tally = [{} for _ in sides]
    for t, data in zip(tally, sides):
        for r in data["runs"]:
            p, n = t.get(r["task_id"], (0, 0))
            t[r["task_id"]] = (p + r["success"], n + 1)
    names = [d["meta"]["agent"] for d in sides]
    print(f"| task | A: {names[0]} | B: {names[1]} |\n| --- | --- | --- |")
    for task in sorted(set(tally[0]) | set(tally[1])):
        cells = [f"{t[task][0]}/{t[task][1]}" if task in t else "-" for t in tally]
        print(f"| {task} | {cells[0]} | {cells[1]} |")
    totals = [f"{sum(p for p, _ in t.values())}/{sum(n for _, n in t.values())}" for t in tally]
    print(f"| **total** | **{totals[0]}** | **{totals[1]}** |")


def main() -> None:
    p = argparse.ArgumentParser(prog="ekg")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the agent, score every step with Jev, write a report")
    r.add_argument("--agent", choices=["scripted", "openrouter"], default="scripted")
    r.add_argument("--model", default="openai/gpt-4.1-mini", help="OpenRouter model id (for --agent openrouter)")
    r.add_argument("--repeats", type=int, default=5, help="runs per task")
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--tasks", nargs="*", help="only these task ids")
    r.add_argument("--tier", choices=["all", "easy", "hard"], default="all")
    r.add_argument("--out", type=Path, help="output directory (default results/<timestamp>)")
    r.add_argument("--breaker", type=float, metavar="THRESHOLD",
                   help="circuit breaker: block side-effecting tool calls Jev allows with probability below this")
    rep = sub.add_parser("report", help="re-render a report from a results directory")
    rep.add_argument("dir", type=Path)
    cmp = sub.add_parser("compare", help="compare per-task pass rates of two results directories")
    cmp.add_argument("a", type=Path)
    cmp.add_argument("b", type=Path)
    a = p.parse_args()

    if a.cmd == "compare":
        compare(a.a, a.b)
        return

    if a.cmd == "report":
        data = json.loads((a.dir / "runs.json").read_text())
        write_report(a.dir, data["runs"], data["meta"])
        print(f"wrote {a.dir / 'report.html'}")
        return

    jev = Jev()
    breaker = Breaker(jev, a.breaker) if a.breaker is not None else None
    agent = OpenRouterAgent(a.model, breaker) if a.agent == "openrouter" else ScriptedAgent(breaker)
    label = a.model if a.agent == "openrouter" else "scripted demo agent"
    if breaker:
        label += f" + circuit breaker ({a.breaker:g})"
    now = dt.datetime.now()
    out = a.out or Path("results") / now.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    tasks = select_tasks(a.tasks, a.tier)
    print(f"Running {label} on {len(tasks)} tasks × {a.repeats} repeats")
    runs = asyncio.run(run_all(agent, jev, tasks, a.repeats, a.seed))
    if not runs:
        raise SystemExit("No runs completed; nothing to report.")
    stats = write_report(out, runs, {"agent": label, "created": now.strftime("%Y-%m-%d %H:%M"), "breaker": a.breaker})
    b = stats["best"]
    print(f"\n{stats['passed']}/{stats['runs']} runs passed. Stopping below P(on track) {b['threshold']:g} catches "
          f"{b['caught_rate']:.0%} of failures, stops {b['false_kills']} good runs, saves "
          f"{b['tokens_saved_rate']:.0%} of agent tokens. Jev cost ${stats['jev_cost_usd']:.4f}.")
    print(f"Report: {out / 'report.html'}")
