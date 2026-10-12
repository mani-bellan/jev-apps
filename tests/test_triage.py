"""Triage policy tests against a fake Jev API, so they run without an API key or network."""

import httpx2
import pytest
from typesafe_sdk import TypeSafeClient

from triage import triage


def fake_jev(cause: str, confidence: float, impact: float) -> TypeSafeClient:
    answers = {
        "cause": {"type": "choice", "choice": cause, "confidence": confidence, "probabilities": {cause: confidence}},
        "impact": {"type": "score", "score": impact, "confidence": 1.0, "legend": {}, "probabilities": {}},
    }
    body = {"model": "jev-test", "answers": answers, "usage": {"input_tokens": 1, "output_tokens": 1}}
    return TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body)))


@pytest.mark.parametrize(
    ("cause", "confidence", "impact", "attempt", "action"),
    [
        # A cause Jev cannot see goes to a human, however sure it is about that.
        ("unknown", 1.0, 0.0, 1, "review"),
        # Just under the confidence floor goes to a human; at the floor, the automation acts.
        ("network", 0.59, 0.0, 1, "review"),
        ("network", 0.6, 2.0, 2, "retry"),
        # Out of attempts: no retry, and low impact opens a ticket.
        ("network", 1.0, 0.0, 3, "ticket"),
        # Out of attempts: no retry, and high impact pages on-call.
        ("resources", 1.0, 1.5, 3, "page"),
        # Causes that need a fix are never retried.
        ("credentials", 1.0, 1.49, 1, "ticket"),
    ],
)
def test_triage_policy(cause: str, confidence: float, impact: float, attempt: int, action: str) -> None:
    failure = {"pipeline": "orders_daily", "task": "load", "attempt": attempt, "error_log": "..."}

    assert triage(fake_jev(cause, confidence, impact), failure).action == action
