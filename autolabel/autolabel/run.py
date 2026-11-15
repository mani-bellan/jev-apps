"""Asks a backend both questions about every complaint in a split. Results append to
results/<backend>/<split>.jsonl one line per complaint, so an interrupted run resumes where it stopped."""

import asyncio
import json
from pathlib import Path

from .data import load
from .deciders import Decider
from .questions import questions, state, taxonomy

RESULTS = Path(__file__).resolve().parent.parent / "results"


def results_path(backend: str, split: str) -> Path:
    return RESULTS / backend / f"{split}.jsonl"


def read_results(backend: str, split: str) -> dict[str, dict]:
    path = results_path(backend, split)
    if not path.exists():
        return {}
    return {r["id"]: r for r in map(json.loads, path.read_text().splitlines()) if r}


async def run(backend: str, split: str, concurrency: int, limit: int | None = None) -> Path:
    records = load(split)[:limit] if limit else load(split)
    done = read_results(backend, split)
    todo = [r for r in records if r["id"] not in done]
    path = results_path(backend, split)
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"{backend} · {split}: {len(records)} complaints, {len(done)} already done, {len(todo)} to ask")
    issues = taxonomy()
    decider = Decider(backend, concurrency)
    finished = 0

    async def one(r: dict) -> None:
        nonlocal finished
        res = await decider.ask(state(r["text"]), questions(r["product"], issues, decider.backend.describe_options))
        line = {"id": r["id"], **res}
        with path.open("a") as f:
            f.write(json.dumps(line) + "\n")
        finished += 1
        if finished % 25 == 0 or finished == len(todo):
            print(f"  {finished}/{len(todo)}", flush=True)

    try:
        await asyncio.gather(*(one(r) for r in todo))
    finally:
        await decider.close()
    return path


def run_sync(backend: str, split: str, concurrency: int, limit: int | None = None) -> Path:
    return asyncio.run(run(backend, split, concurrency, limit))
