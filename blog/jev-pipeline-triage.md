# Triage pipeline failures in 100 ms with Jev

*Blog · Data engineering · Jev · October 12, 2026 · 8 min read · [Source code on GitHub](https://github.com/mani-bellan/jev-apps)*

We built a small Python app that reads a failed pipeline task and decides, in under a tenth of a second, whether to retry it, open a ticket, page on-call, or ask a human. Then we tested it on real dbt failures, watched it get 3 of 7 right, and fixed it. Here is how it works, what it costs, and what the real logs taught us.

## TL;DR

| | |
|---|---|
| **What we built** | A pipeline failure triage app: one Jev call per failed task answers two typed questions (the cause and the impact), and a few lines of plain Python turn the answers into an action. |
| **Results** | Tested on 18 failures: 8 hand-written and 10 real dbt failures. All 15 failures used during tuning got the right action. Of 3 held-out dbt failures, all 3 got the right action and 2 the right cause. |
| **Speed and cost** | 56–149 ms per decision (median under 80 ms). About $0.00004 per failure, so 10,000 failures a day would cost about $0.40. |
| **Main lesson** | Test on real logs. The hand-written samples passed 8 of 8; the first run on real dbt logs passed 3 of 7. Fixing it meant deleting a question and stating two definitions more precisely. |

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

Because the answer types are fixed, the output can be branched on directly: `if answer.confidence < 0.6`. There is nothing to parse and no malformed response to handle. Input costs $0.042 per million tokens, and output is free.

## One call asks two questions, and code decides what to do

Each failed task is a small JSON object: the pipeline and task name, the attempt number, which datasets depend on it, and the error log. We send that object as the state, with two questions about it.

![The state and the two questions sent to Jev for one real dbt failure](https://raw.githubusercontent.com/mani-bellan/jev-apps/main/blog/images/request.png)

*The request for one real dbt failure. Each label in `cause` also carries a one-line description that Jev reads, such as "Out of memory, disk full, or a worker or executor was killed".*

Jev answers in well under 100 ms. Then a few lines of ordinary Python apply the policy. The model supplies the judgment; your code owns the decision and its thresholds.

![Failed task, one Jev call answering cause and impact in parallel, policy in code, then retry, ticket, page, or review](https://raw.githubusercontent.com/mani-bellan/jev-apps/main/blog/images/triage-flow.png)

*The whole path. Only the middle box is a model; everything after it is code that you can read, test, and change.*

The policy checks four rules, in order:

| If | Then |
|---|---|
| The cause is `unknown`, or the confidence in it is below 0.6 | **Review:** a human reads the log |
| The cause can clear up by itself (network, late upstream data, resources) and attempts are left | **Retry** with a plan for that cause: in 5 minutes, in 30 minutes, or with twice the memory |
| The expected impact is at least 1.5 out of 2 | **Page** on-call for the owning team |
| Anything else | **Ticket** for the owning team |

```python
if cause.choice == "unknown" or cause.confidence < CONFIDENCE_FLOOR:
    action = "review"
elif cause.choice in TRANSIENT and failure["attempt"] < MAX_ATTEMPTS:
    action = "retry"
elif impact >= PAGE_THRESHOLD:
    action = "page"
else:
    action = "ticket"
```

*The core of `triage()` in [`triage.py`](https://github.com/mani-bellan/jev-apps/blob/main/triage.py).*

## Real dbt failures: 3 of 7 on the first run, 10 of 10 actions after fixing

Hand-written logs are easy to get right, because the person writing them leaves clues. So we built a small dbt project on DuckDB (three CSV sources, five models, 13 tests, and three exposures: a finance revenue report, customer invoices, and a marketing list) and a script that breaks it in realistic ways. Each run copies the project, makes one change, runs `dbt build`, and saves the real dbt output as a failure. The `downstream` field comes from dbt's manifest, so the impact question sees which reports actually depend on the broken model.

The first version of the app got **3 of the first 7** right. The cause was right in 6 of them; the decisions were wrong because of a question we should not have asked (Lesson 2 below). After the fixes, all 7 matched. We then added three failures we had not tuned on.

| What we broke | Real dbt error | Jev's answers | Action |
|---|---|---|---|
| A payment exported twice | `unique_stg_payments_payment_id`: Got 1 result | data_quality (1.00), impact 2.0 | 🚨 Page data owners |
| A customer with no email | `not_null_stg_customers_email`: Got 1 result | data_quality (1.00), impact 1.0 | 🎫 Ticket data owners |
| Source column `email` renamed to `email_address` | Binder Error: column "email" not found | schema_change (0.83), impact 1.0 | 🎫 Ticket data owners |
| `group by` typed as `grop by` | Parser Error: syntax error at or near "grop" | code_bug (1.00), impact 1.0 | 🎫 Ticket pipeline owners |
| Today's orders export not landed | IO Error: No files found that match the pattern | upstream_delay (0.99), impact 2.0 | ✅ Retry in 30 min |
| Worker memory limit of 1 MB | Out of Memory Error: could not allocate block | resources (1.00), impact 2.0 | ✅ Retry with 2× memory |
| Exports host unreachable | IO Error: Could not resolve hostname | network (0.95), impact 2.0 | ✅ Retry in 5 min |
| *Held out:* an unknown order status | `accepted_values_stg_orders_status`: Got 1 result | data_quality (1.00), impact 2.0 | 🚨 Page data owners |
| *Held out:* a payment for an order that does not exist | `relationships_stg_payments_order_id`: Got 1 result | data_quality (1.00), impact 2.0 | 🚨 Page data owners |
| *Held out:* an amount exported as `56.00 EUR` | Binder Error: No function matches '/(VARCHAR, DECIMAL)'. You might need to add explicit type casts. | **code_bug** (0.99), impact 2.0 | 🚨 Page pipeline owners |

> ⚠️ **The held-out miss:** the amount column turning into text is a schema change, but Jev called it a code bug, and DuckDB's own message ("you might need to add explicit type casts") points the same way. The action was still right, because finance is affected, but the page went to the pipeline owners instead of the upstream data owners. We left it unfixed: tuning on held-out cases would make them meaningless.

![Latency per triage call on the ten real dbt failures, from 56 ms for the unreachable source to 149 ms for the orphan payment](https://raw.githubusercontent.com/mani-bellan/jev-apps/main/blog/images/latency.png)

*Latency per triage call on the ten real dbt failures, including the network round trip. Median 78 ms. Each call used 849–1,469 input tokens.*

> **Cost at scale:** about 984 tokens × $0.042 per million is $0.00004 per failure. A platform with 10,000 failures a day would spend about $0.40 a day on triage.

The eight hand-written failures from our first version (a HubSpot timeout, a Spark out-of-memory error on its last attempt, an expired Google token, a log that only says "Task exited with return code 1", and others) still all get the right action with the final questions, at a median of 66 ms.

## What we learned getting it right

### Lesson 1: Test on real logs, not the samples you wrote

Our hand-written logs carried clues a real log does not, such as "the upstream export usually lands by 02:00 UTC". With them, the app passed 8 of 8. The real dbt log for the same problem says only "No files found that match the pattern", and the app passed 3 of 7. Generating real failures took one short script and caught both of the problems below.

### Lesson 2: Delete questions your policy does not need

Our first version also asked whether "re-running the task without any change" would succeed, and retried only above 0.5. For the out-of-memory failure, Jev answered 0.16, which is correct: our retry plan adds memory, which is a change. For the missing partition and the unreachable host, it answered about 0.2, because nothing in those logs says whether the data or the host will come back. But the cause already tells us whether a retry makes sense, and attempts are capped at three. Deleting the question fixed three of the four wrong decisions and made each call faster.

### Lesson 3: Put the clues a human uses into the descriptions

The renamed column was called a code bug with 0.91 confidence. A data engineer spots a schema change from the hint "Candidate bindings: email_address", so we wrote that clue into the `schema_change` description: a column the query reads is not found, often with a similar column suggested. The same goes for policy: "customer-facing data" also matched a marketing newsletter, so a missing email scored right at the page threshold (1.4 to 1.6 across runs). Saying that a marketing list is moderate impact moved it to about 1.0.

Wording matters in general. In the support router, rewording one question raised "I forgot my password" from 0.27 to 0.84 for the account agent. Compare a few wordings on labelled examples before you choose; it takes minutes and costs a fraction of a cent.

### Lesson 4: Give the model a way to say "I can't tell"

Our first version relied on confidence alone to catch unclear logs. It failed: for a log that said only "Task exited with return code 1", Jev picked `code_bug` with 0.86 confidence. Confidence measures how sure the model is between the options you gave it, so when none of them fit, it can still be sure. Adding an explicit `unknown` option fixed it.

![Before: the log is classified as code_bug with 0.86 confidence and becomes a ticket. After: it is classified as unknown with 1.00 confidence and goes to human review](https://raw.githubusercontent.com/mani-bellan/jev-apps/main/blog/images/unknown-before-after.png)

*Same log, same policy. Only the list of possible causes changed.*

### Lesson 5: Test the policy against a fake API, at the boundaries

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

- **Eighteen failures are a demo, not an evaluation.** Ten are real dbt failures, but we broke the project ourselves and tuned the questions on fifteen of the eighteen. Before trusting the policy, run it in shadow mode on your own failure history and compare its decisions with what your team actually did.
- **Cause errors send work to the wrong team.** The held-out type change was paged to the pipeline owners instead of the data owners. Include who owns what in the ticket or page, so a misrouted alert is quick to hand over.
- **Jev does not write text.** It cannot draft the ticket body or extract a value it was not offered. Pair it with regex or an LLM when you need either.
- **Pin the model version.** The probabilities can shift between versions, and your thresholds depend on them. Use `jev-1.13.0`, not `jev-latest`, in production.
- **It is early.** Jev is in early access, and TypeSafe notes that rate limits (currently 100K tokens and 80 requests per second) are changing.

## Try it

All the code is on GitHub at [github.com/mani-bellan/jev-apps](https://github.com/mani-bellan/jev-apps): a few hundred lines of Python using the official `typesafe-sdk` package. Clone it and run it with your own API key from [console.typesafe.ai](https://console.typesafe.ai/keys):

| File | What it holds |
|---|---|
| [`triage.py`](https://github.com/mani-bellan/jev-apps/blob/main/triage.py) | The two questions, the policy in `triage()`, and the dry-run `dispatch()` |
| [`dbt_demo/`](https://github.com/mani-bellan/jev-apps/tree/main/dbt_demo) | The dbt project and `run_scenarios.py`, which breaks it, captures the real failures, and scores the triage app |
| [`samples/`](https://github.com/mani-bellan/jev-apps/tree/main/samples) | The eight hand-written failures, and the ten real dbt failures in `samples/dbt/` |
| [`router.py`](https://github.com/mani-bellan/jev-apps/blob/main/router.py), [`agents.py`](https://github.com/mani-bellan/jev-apps/blob/main/agents.py) | The customer support router and its agents |
| [`tests/`](https://github.com/mani-bellan/jev-apps/tree/main/tests) | Policy and routing tests against a fake Jev API |

```bash
git clone https://github.com/mani-bellan/jev-apps && cd jev-apps
export TYPESAFE_API_KEY=...                   # your own key; never commit it
uv run triage.py samples/dbt/*.json           # triage the real dbt failures
uv run --group dbt dbt_demo/run_scenarios.py  # break dbt, capture, and score
uv run main.py "I forgot my password"         # customer support router
uv run pytest                                 # tests, no key needed
```

The actions are a dry run. To go live, replace the prints in `dispatch()` with calls to your scheduler, ticketing, and paging tools.
