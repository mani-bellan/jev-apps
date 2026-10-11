# Jev apps

Two small Python apps built on [Jev](https://docs.typesafe.ai/introduction), TypeSafe AI's
decision model.

- **Pipeline failure triage** (`triage.py`): decides what to do about a failed data-pipeline task.
- **Customer support router** (`main.py`): routes customer messages to specialist agents.

Read the write-up: [Triage pipeline failures in 100 ms with Jev](blog/jev-pipeline-triage.md).

## API key

Both apps read your key from the `TYPESAFE_API_KEY` environment variable (get one at
https://console.typesafe.ai/keys). The key is never stored in this repository. Set it in your
shell, or put it in a `.env` file, which `.gitignore` excludes:

```bash
export TYPESAFE_API_KEY=...
# or
echo 'TYPESAFE_API_KEY=...' > .env && uv run --env-file .env triage.py samples/*.json
```

## Pipeline failure triage

One Jev call per failed task answers three questions together. Code in `triage()` turns the
answers into one action:

| Jev answers | Action |
|---|---|
| cause is `unknown`, or confidence in the cause < 0.6 | **review** by a human |
| cause is transient (network, late upstream data, resources), retry likely to succeed ≥ 0.5, attempts left | **retry** with a cause-specific plan |
| expected impact ≥ 1.5 on a 0–2 scale | **page** on-call for the owning team |
| anything else | **ticket** for the owning team |

```bash
uv run triage.py samples/*.json
```

```
samples/oom_retries_exhausted.json  (billing_usage.aggregate_usage_events, attempt 3/3)
  Jev: cause resources (1.00 confidence), retry will succeed 0.38, impact 2.0/2
  → PAGE on-call for the platform team: billing_usage.aggregate_usage_events failed (resources)
```

A failure is a JSON object with `pipeline`, `task`, `attempt`, and `error_log`; any other fields,
such as `downstream`, are context that Jev reads too. Actions are a dry run: replace the prints
in `dispatch()` with your scheduler, ticketing, and paging APIs (for example Airflow, Jira, and
PagerDuty). Causes, owners, and thresholds are constants at the top of `triage.py`.

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

## Test

```bash
uv run pytest
```

The tests use a fake Jev API, so they need no key or network.
