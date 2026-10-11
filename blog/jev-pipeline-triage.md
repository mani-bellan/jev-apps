# Triage pipeline failures in 100 ms with Jev

*Blog · Data engineering · Jev · October 11, 2026 · 7 min read · [Source code on GitHub](https://github.com/mani-bellan/jev-apps)*

We built a small Python app that reads a failed pipeline task and decides, in about a tenth of a second, whether to retry it, open a ticket, page on-call, or ask a human. Here is how it works, what it costs, and what we learned getting it right.

## TL;DR

| | |
|---|---|
| **What we built** | A pipeline failure triage app: one Jev call per failed task answers three typed questions, and a few lines of plain Python turn the answers into an action. |
| **Results** | All 8 sample failures got the expected action. Each call took 78–169 ms (median 101 ms). |
| **Cost** | About 723 input tokens per failure, which is $0.00003. Ten thousand failures a day would cost about $0.30. |
| **Main lesson** | Let the model make narrow judgments and keep the policy in your code. Give it an explicit "unknown" answer, because confidence alone does not catch a log with no clues in it. |

## Most pipeline failures need a decision, not an investigation

Every data team knows the pattern. A DAG fails at 3 a.m., someone gets paged, opens the logs, and finds a network timeout that a retry would have fixed. Or a renamed column that the upstream team needs to hear about. Or a dbt test on finance data that really does need a person right now.

The decision is usually quick for a human who reads the log, but it is hard to write as rules. Error messages come from Spark, Snowflake, dbt, Python, and every API you call, and they change with each library upgrade. Regex rules rot, and blanket retry policies either retry things that can never succeed or give up on things that would.

A chat LLM can read the log, but it answers in text. You then parse that text, handle the cases where it wanders off format, and wait seconds per call. That is fine for one failure and a poor fit for a step that runs on every failure in your platform.

## Jev answers typed questions instead of writing text

[Jev](https://docs.typesafe.ai/introduction) is a new model from TypeSafe AI that never generates text. You send it some **state** (text or JSON) and a set of **questions** whose possible answers you define in advance. It answers all of them in one parallel pass, and every answer comes back with probabilities. There are three question types:

| Type | Asks | Returns |
|---|---|---|
| `choice` | Which of these labels fits? (up to 255 labels) | The chosen label, the probability of every label, and a confidence |
| `noul` | Is this statement true? | The probability that it is true |
| `score` | Where does this fall on an ordered scale of 2–10 levels? | An expected score and the probability of each level |

Because the answer types are fixed, the output can be branched on directly: `if answer.noul >= 0.5`. There is nothing to parse and no malformed response to handle. Input costs $0.042 per million tokens, and output is free.

## One call asks three questions, and code decides what to do

Each failed task is a small JSON object: the pipeline and task name, the attempt number, which datasets depend on it, and the error log. We send that object as the state, with three questions about it.

![The state and the three questions sent to Jev for one sample failure](https://raw.githubusercontent.com/mani-bellan/jev-apps/main/blog/images/request.png)

*The request for one real sample. Each label in `cause` also carries a one-line description that Jev reads, such as "Out of memory, disk full, or a worker or executor was killed".*

Jev answers in about 100 ms. Then a few lines of ordinary Python apply the policy. The model supplies the judgment; your code owns the decision and its thresholds.

![Failed task, one Jev call answering cause, retry odds, and impact in parallel, policy in code, then retry, ticket, page, or review](https://raw.githubusercontent.com/mani-bellan/jev-apps/main/blog/images/triage-flow.png)

*The whole path. Only the middle box is a model; everything after it is code that you can read, test, and change.*

The policy checks four rules, in order:

| If | Then |
|---|---|
| The cause is `unknown`, or the confidence in it is below 0.6 | **Review:** a human reads the log |
| The cause can clear up by itself (network, late upstream data, resources), the retry odds are at least 0.5, and attempts are left | **Retry** with a plan for that cause: in 5 minutes, in 30 minutes, or with twice the memory |
| The expected impact is at least 1.5 out of 2 | **Page** on-call for the owning team |
| Anything else | **Ticket** for the owning team |

```python
if cause.choice == "unknown" or cause.confidence < CONFIDENCE_FLOOR:
    action = "review"
elif (cause.choice in TRANSIENT and retry >= RETRY_THRESHOLD
      and failure["attempt"] < MAX_ATTEMPTS):
    action = "retry"
elif impact >= PAGE_THRESHOLD:
    action = "page"
else:
    action = "ticket"
```

*The core of `triage()` in [`triage.py`](https://github.com/mani-bellan/jev-apps/blob/main/triage.py).*

## All eight sample failures got the right action

We wrote eight realistic failures, one for each kind of problem plus one log with no useful information, and ran them against the live API. Two runs gave identical decisions.

| Failure | Jev's answers | Action |
|---|---|---|
| HubSpot API read timeout and a 503 | network (1.00), retry 0.68 | ✅ Retry in 5 min |
| S3 partition for today not there yet | upstream_delay (1.00), retry 0.84 | ✅ Retry in 30 min |
| Spark out of memory on attempt 3/3, feeds customer invoices | resources (1.00), impact 2.0 | 🚨 Page platform |
| dbt `unique` test failed on payments, feeds regulatory filings | data_quality (0.99), impact 2.0 | 🚨 Page data owners |
| Snowflake "invalid identifier" after a source column was renamed | schema_change (0.99), impact 1.0 | 🎫 Ticket data owners |
| Google token expired or revoked | credentials (1.00), impact 1.0 | 🎫 Ticket platform |
| Python `TypeError` right after a deploy | code_bug (1.00), impact 1.0 | 🎫 Ticket pipeline owners |
| Only "Task exited with return code 1" | unknown (1.00) | 👀 Human review |

Each failure takes one call. Measured from our sandbox after one warm-up call:

![Latency per triage call, from 78 ms for the schema change to 169 ms for the out-of-memory failure](https://raw.githubusercontent.com/mani-bellan/jev-apps/main/blog/images/latency.png)

*Latency per triage call, including the network round trip. Median 101 ms. Each call used 686–762 input tokens.*

> **Cost at scale:** 723 tokens × $0.042 per million is $0.00003 per failure. A platform with 10,000 failures a day would spend about $0.30 a day on triage.

## What we learned getting it right

### Lesson 1: Give the model a way to say "I can't tell"

Our first version relied on confidence alone to catch unclear logs. It failed: for a log that said only "Task exited with return code 1", Jev picked `code_bug` with 0.86 confidence, and the failure went to the pipeline owners as a ticket. Confidence measures how sure the model is between the options you gave it, so when none of them fit, it can still be sure. Adding an explicit `unknown` option fixed it.

![Before: the log is classified as code_bug with 0.86 confidence and becomes a ticket. After: it is classified as unknown with 1.00 confidence and goes to human review](https://raw.githubusercontent.com/mani-bellan/jev-apps/main/blog/images/unknown-before-after.png)

*Same log, same policy. Only the list of possible causes changed.*

### Lesson 2: Wording matters, so test it on a small labelled set

We first built a customer support router with the same approach, and asked Jev whether a message "includes a request for the account team". For "I forgot my password" that scored only 0.27. Rewording it to "resolving this message requires the account team" raised it to 0.84. We compared three wordings on eight labelled messages in a short script before choosing one; it took a few minutes and cost a fraction of a cent.

### Lesson 3: Thresholds are business decisions, so keep them in code

The HubSpot timeout scored 0.68 for "a retry will succeed", just under our first threshold of 0.7, so it became a ticket. We lowered the threshold to 0.5 because retries are cheap and capped at three attempts. That was a policy choice, not a model fix, and it took one constant. The expired token scored 0.48 but is never retried, because credentials are not a cause that clears up by itself.

### Lesson 4: Test the policy against a fake API, at the boundaries

The Python SDK accepts a custom HTTP transport, so the tests serve fixed Jev answers through the real client with no key or network. Each case sits on a threshold, such as confidence 0.59 against 0.6. We broke each rule on purpose, one at a time, and a test failed every time.

## The same pattern routes messages to several agents at once

The other app in the repository routes customer messages. One Jev call asks a yes/no question per agent (billing, technical, account, sales) plus "is this urgent?". Every agent that scores at least 0.5 is called, so "My Stripe integration keeps failing and I also need an invoice" reaches both the billing and technical agents. Each agent then makes its own Jev call to pick an action. A full route with two agents took about 260 ms.

![A customer message goes through one router call; billing (0.86) and technical (0.85) are called, account (0.09) and sales (0.13) are not](https://raw.githubusercontent.com/mani-bellan/jev-apps/main/blog/images/support-router.png)

*A real run. Yes/no questions instead of a single choice let one message reach more than one agent.*

## Where else this fits in data engineering

The pattern fits any step that needs a judgment a rule cannot make reliably and that runs at volume. Because a decision costs a few hundred-thousandths of a dollar, you can run it on every row or event instead of a sample.

- **Alert noise filtering:** is this alert actionable, and how severe is it?
- **Record categorization in ETL:** transactions, products, or tickets mapped to your labels, with low-confidence rows sent to a review table.
- **Data quality on free text:** is this a real address, or a placeholder such as "N/A" or "test"?
- **Duplicate matching:** are these two candidate records the same customer?
- **Column mapping during ingestion:** which target field does this source column map to?
- **PII detection:** does this column contain personal data, and of what kind?

## Limits to keep in mind

- **Eight samples are a demo, not an evaluation.** We wrote them ourselves. Before trusting the policy, run it in shadow mode on your own failure history and compare its decisions with what your team actually did.
- **Jev does not write text.** It cannot draft the ticket body or extract a value it was not offered. Pair it with regex or an LLM when you need either.
- **Pin the model version.** The probabilities can shift between versions, and your thresholds depend on them. Use `jev-1.13.0`, not `jev-latest`, in production.
- **It is early.** Jev is in early access, and TypeSafe notes that rate limits (currently 100K tokens and 80 requests per second) are changing.

## Try it

All the code is on GitHub at [github.com/mani-bellan/jev-apps](https://github.com/mani-bellan/jev-apps): a few hundred lines of Python using the official `typesafe-sdk` package. Clone it and run it with your own API key from [console.typesafe.ai](https://console.typesafe.ai/keys):

| File | What it holds |
|---|---|
| [`triage.py`](https://github.com/mani-bellan/jev-apps/blob/main/triage.py) | The three questions, the policy in `triage()`, and the dry-run `dispatch()` |
| [`samples/`](https://github.com/mani-bellan/jev-apps/tree/main/samples) | The eight failure logs used in this post |
| [`router.py`](https://github.com/mani-bellan/jev-apps/blob/main/router.py), [`agents.py`](https://github.com/mani-bellan/jev-apps/blob/main/agents.py) | The customer support router and its agents |
| [`tests/`](https://github.com/mani-bellan/jev-apps/tree/main/tests) | Policy and routing tests against a fake Jev API |

```bash
git clone https://github.com/mani-bellan/jev-apps && cd jev-apps
export TYPESAFE_API_KEY=...            # your own key; never commit it
uv run triage.py samples/*.json        # pipeline failure triage
uv run main.py "I forgot my password"  # customer support router
uv run pytest                          # tests, no key needed
```

The actions are a dry run. To go live, replace the prints in `dispatch()` with calls to your scheduler, ticketing, and paging tools.
