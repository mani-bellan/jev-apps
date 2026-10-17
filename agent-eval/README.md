# Agent EKG: agent evaluation with Jev

Most agent evals grade the final answer. Agent EKG scores **every step** of every run with
[Jev](https://docs.typesafe.ai/concepts/system-one), TypeSafe's System One model, and draws each run's
"heartbeat": the probability that the agent is still on track after each tool call.

That answers questions final-answer evals can't:

- **Where did it go wrong?** The step where the heartbeat drops.
- **How early can we tell?** Share of failing runs flagged within the first N steps, and the AUC of the
  heartbeat as a failure predictor after each step.
- **What would a monitor save?** Every run is replayed with a monitor that stops it at the first step below a
  threshold: failures caught, good runs wrongly stopped, agent tokens saved.

Scoring every step with an LLM judge is too expensive to do routinely. Jev costs $0.042 per million input tokens and
answers in about 150 ms, so the demo scores ~200 steps for about one cent.

Pass/fail comes from deterministic checks on the final world state. Jev never sees them.

## Run it

```shell
cd agent-eval
export TYPESAFE_API_KEY=...            # Jev
uv run ekg run                          # scripted demo agent, all 18 tasks x 5 repeats
uv run ekg run --tier hard              # only the hard tasks
```

With a real LLM agent (any tool-calling model on OpenRouter):

```shell
export OPENROUTER_API_KEY=...
uv run ekg run --agent openrouter --model openai/gpt-4.1-mini --repeats 5
```

Paid models need OpenRouter credits. Free models (ids ending in `:free`, e.g.
`nvidia/nemotron-3-super-120b-a12b:free`) work without credits but are limited to about 50 requests a day;
a run uses roughly 3–4 requests per task. Runs that keep failing on rate limits are skipped, not fatal.

Each run writes `results/<timestamp>/` with `runs.json` (trajectories and per-step scores), `stats.json` and
`report.html`. Re-render a report with `uv run ekg report results/<dir>`.

## Circuit breaker

The heartbeat only sees a mistake after the tool has run. With `--breaker THRESHOLD`, every tool call that
changes the world (`send_email`, `book_flight`, `create_event`, `update_event`, `delete_event`, `clear_day`,
`delete_file`) is first sent to Jev together with the run so far: *should this action run?* Calls Jev allows
with probability below the threshold are not executed; the agent gets a "blocked by safety monitor" tool error
and can verify, choose another action, or ask the user. Read-only tools are never checked.

```shell
uv run ekg run --agent openrouter --model <model> --tier hard --out results/plain
uv run ekg run --agent openrouter --model <model> --tier hard --breaker 0.4 --out results/breaker
uv run ekg compare results/plain results/breaker     # per-task pass rates, side by side
```

Calibration on this repo's tasks (each correct side-effecting call and each trap call, at the point in the run
where it happens): at 0.4 the breaker blocked 0 of 16 correct calls and 25 of 26 traps; the one it let through
was emailing the wrong Rahul (allow 0.43). Each check took 110–460 ms. With the scripted agent and the same seed,
the breaker raised the pass rate from 60/90 to 67/90 and turned no passing run into a failure. The threshold was
chosen on these same tasks, so check it on your own.

## How it works

| File | Role |
| --- | --- |
| `ekg/world.py` | Mocked assistant world (calendar, inbox, contacts, files, flights) and 16 tools |
| `ekg/tasks.py` | 10 easy tasks with traps (look-alike flights, wrong contacts, destructive tools) and 8 hard ones (prompt injection in an email or file, flaky tools, a long multi-step chain, ambiguous and conflicting information), each with a checker |
| `ekg/agents.py` | `OpenRouterAgent` (real tool-calling loop) and `ScriptedAgent` (no key needed) |
| `ekg/jev.py` | Scores every prefix of a run: `on_track` (yes/no probability) and `last_step` (progress / neutral / mistake / harmful); `Breaker` asks whether a proposed action should run |
| `ekg/analysis.py` | Derail points, early-warning AUC, early-stop replay |
| `ekg/report.py` | Self-contained HTML report |

The scripted agent follows each task's correct plan but randomly injects detours, loops, trap actions, early
quits with a hallucinated success message, and wrong answers. It exists to exercise the pipeline without an LLM
key; publish numbers from real models only.

## Ideas to take further

- **Rewind and retry:** fork a failed run at its derail step with a hint or a stronger model and measure recovery.
- **Model leaderboard:** compare heartbeats across models; some fail fast, others wander.
- **Calibration:** label a few dozen runs by hand and fit thresholds to your own data.
