"""Triage failed data-pipeline tasks with Jev, then retry, open a ticket, page on-call, or ask a human.

    uv run triage.py samples/*.json
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from typesafe_sdk import Choice, Score, TypeSafeClient, TypeSafeError

CAUSES = {
    "network": "Timeouts, connection resets, rate limits, or 5xx errors from an external service",
    "upstream_delay": "Expected input data, file, or partition is missing or has not arrived yet",
    "resources": "Out of memory, disk full, or a worker or executor was killed",
    "schema_change": (
        "A source added, removed, renamed, or changed the type of a column. Typical sign: a column the query"
        " reads is not found, often with a similarly named column suggested instead"
    ),
    "data_quality": "A data test or constraint failed: nulls, duplicates, or out-of-range values",
    "credentials": "Authentication or permission errors, or expired tokens, passwords, or keys",
    "code_bug": "A mistake in our own pipeline code that needs a code fix, such as a SQL syntax error or a bug in a transform",
    "unknown": "The log does not contain enough information to tell what went wrong",
}
TRANSIENT = {"network", "upstream_delay", "resources"}
"""Causes that can clear up by themselves, so they are retried while attempts remain."""
RETRY_PLAN = {
    "network": "retry in 5 minutes",
    "upstream_delay": "retry in 30 minutes, when the input should have landed",
    "resources": "retry with twice the memory",
}
OWNERS = {
    "network": "platform team",
    "upstream_delay": "upstream data owners",
    "resources": "platform team",
    "schema_change": "upstream data owners",
    "data_quality": "upstream data owners",
    "credentials": "platform team",
    "code_bug": "pipeline owners",
}

QUESTIONS = {
    "cause": Choice(instructions="The root cause of this pipeline task failure", criteria=CAUSES),
    "impact": Score(
        instructions="How badly this failure affects the consumers of the pipeline's data",
        criteria=[
            "Little impact: internal, exploratory, or rarely used data",
            "Moderate impact: a routine report, dashboard, or marketing list will be late",
            "Severe impact: invoices, billing, finance, regulatory reporting, or a customer-facing product is wrong or blocked",
        ],
    ),
}

CONFIDENCE_FLOOR = 0.6
"""Below this confidence in the cause, a human decides instead of the automation."""
PAGE_THRESHOLD = 1.5
"""Page on-call when the expected impact score (0 to 2) is at least this."""
MAX_ATTEMPTS = 3


@dataclass
class Decision:
    action: str
    """One of "retry", "page", "ticket", or "review"."""
    detail: str
    cause: str
    cause_confidence: float
    impact: float


def triage(client: TypeSafeClient, failure: dict) -> Decision:
    response = client.system_one(failure, QUESTIONS)
    cause = response.choices["cause"]
    impact = response.scores["impact"].score

    if cause.choice == "unknown" or cause.confidence < CONFIDENCE_FLOOR:
        action, detail = "review", "the cause is unclear, so a human should look at the logs"
    elif cause.choice in TRANSIENT and failure["attempt"] < MAX_ATTEMPTS:
        action, detail = "retry", RETRY_PLAN[cause.choice]
    elif impact >= PAGE_THRESHOLD:
        action, detail = "page", f"on-call for the {OWNERS[cause.choice]}"
    else:
        action, detail = "ticket", f"for the {OWNERS[cause.choice]}"
    return Decision(action, detail, cause.choice, cause.confidence, impact)


def dispatch(failure: dict, decision: Decision) -> None:
    """Carry out the decision. Dry run: replace the prints with your scheduler, ticketing, and paging APIs."""
    task = f"{failure['pipeline']}.{failure['task']}"
    match decision.action:
        case "retry":
            print(f"  → RETRY {task}: {decision.detail}")
        case "page":
            print(f"  → PAGE {decision.detail}: {task} failed ({decision.cause})")
        case "ticket":
            print(f"  → TICKET {decision.detail}: {task} failed ({decision.cause})")
        case "review":
            print(f"  → REVIEW: {decision.detail}")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: uv run triage.py FAILURE.json [...]")
    try:
        client = TypeSafeClient()  # reads TYPESAFE_API_KEY from the environment
    except TypeSafeError as error:
        sys.exit(f"Could not create the Jev client: {error}")

    with client:
        for path in sys.argv[1:]:
            failure = json.loads(Path(path).read_text())
            decision = triage(client, failure)
            print(f"{path}  ({failure['pipeline']}.{failure['task']}, attempt {failure['attempt']}/{MAX_ATTEMPTS})")
            print(
                f"  Jev: cause {decision.cause} ({decision.cause_confidence:.2f} confidence), impact {decision.impact:.1f}/2"
            )
            dispatch(failure, decision)


if __name__ == "__main__":
    main()
