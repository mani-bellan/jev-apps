# Jev apps

Three small Python apps built on [Jev](https://docs.typesafe.ai/introduction), TypeSafe AI's
decision model.

- **Pipeline failure triage** (`triage.py`): decides what to do about a failed data-pipeline task.
- **Customer support router** (`main.py`): routes customer messages to specialist agents.
- **Agent EKG** ([`agent-eval/`](agent-eval)): an agent evaluation app that scores every step of every
  agent run with Jev, finds where runs derail, and measures how early failing runs can be stopped.

Read the write-up: [Triage pipeline failures in 100 ms with Jev](blog/jev-pipeline-triage.md).

## API key

All apps read your key from the `TYPESAFE_API_KEY` environment variable (get one at
https://console.typesafe.ai/keys). The key is never stored in this repository. Set it in your
shell, or put it in a `.env` file, which `.gitignore` excludes:

```bash
export TYPESAFE_API_KEY=...
# or
echo 'TYPESAFE_API_KEY=...' > .env && uv run --env-file .env triage.py samples/*.json
```

## Pipeline failure triage

One Jev call per failed task answers two questions together: the root cause (a `choice`) and the
impact on downstream data (a `score`). Code in `triage()` turns the answers into one action:

| Jev answers | Action |
|---|---|
| cause is `unknown`, or confidence in the cause < 0.6 | **review** by a human |
| cause can clear up by itself (network, late upstream data, resources) and attempts are left | **retry** with a cause-specific plan |
| expected impact ≥ 1.5 on a 0–2 scale | **page** on-call for the owning team |
| anything else | **ticket** for the owning team |

```bash
uv run triage.py samples/*.json samples/dbt/*.json
```

```
samples/dbt/duplicate_payment.json  (shop_dbt.unique_stg_payments_payment_id, attempt 1/3)
  Jev: cause data_quality (1.00 confidence), impact 2.0/2
  → PAGE on-call for the upstream data owners: shop_dbt.unique_stg_payments_payment_id failed (data_quality)
```

A failure is a JSON object with `pipeline`, `task`, `attempt`, and `error_log`; any other fields,
such as `downstream`, are context that Jev reads too. Actions are a dry run: replace the prints
in `dispatch()` with your scheduler, ticketing, and paging APIs (for example Airflow, Jira, and
PagerDuty). Causes, owners, and thresholds are constants at the top of `triage.py`.

`samples/*.json` are eight hand-written failures. `samples/dbt/*.json` are ten real dbt failures,
captured from the demo project below.

## Real dbt failures (`dbt_demo/`)

A small dbt project on DuckDB: three CSV sources, five models, 13 tests, and three exposures
(finance report, customer invoices, marketing list). `run_scenarios.py` breaks it ten realistic
ways (duplicate key, missing email, renamed source column, SQL typo, missing partition, out of
memory, unreachable source, and three held-out cases), runs `dbt build`, and saves each real
failure to `samples/dbt/`, with the downstream models and exposures read from dbt's manifest.
With `TYPESAFE_API_KEY` set, it then runs the triage app on each failure and scores it against
the expected cause and action.

```bash
uv run --group dbt dbt_demo/run_scenarios.py
```

## Customer support router

Routes customer messages to specialist agents.

```
message ──▶ Router: one Jev call ──▶ every agent with probability ≥ 0.5 ──▶ replies
            (a yes/no per agent,      (each agent asks Jev which
             plus "is it urgent?")     of its actions fits)
                     │
                     └──▶ human, when no agent matches or urgency ≥ 0.7
```

One message can need several agents, for example "I was charged twice and can't log in"
goes to both `billing` and `account`.

### Run it

```bash
uv run main.py "I was charged twice and the Stripe integration keeps failing"
uv run main.py                # interactive mode
```

Example output (probabilities will vary):

```
Routing: billing 0.97 ✓, technical 0.81 ✓, account 0.03, sales 0.02 | urgency 0.12
[billing agent] I've opened a refund review. Duplicate charges are usually reversed within 5 business days.
[technical agent] Please reconnect the integration from Settings → Integrations and send us the error code if it fails again.
```

### Change the agents

Agents live in `agents.py`. Add an `Agent` to `AGENTS` with a `description` (what the router
shows Jev) and its `actions`. To make an agent do real work, such as calling an LLM, an API, or
a database, subclass `Agent` and override `handle`.

Thresholds are at the top of `router.py`.

## Agent EKG (`agent-eval/`)

A self-contained app with its own `pyproject.toml`. It runs tool-calling agents on 18 tasks with traps
(prompt injection, flaky tools, ambiguous requests), asks Jev after every step whether the agent is still
on track, and writes an HTML report with per-run heartbeats and an early-stop replay. See
[`agent-eval/README.md`](agent-eval/README.md).

```bash
cd agent-eval && uv run ekg run --tier hard
```

## Test

```bash
uv run pytest
```

The tests use a fake Jev API, so they need no key or network.
