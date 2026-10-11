"""Triage policy tests against a fake Jev API, so they run without an API key or network."""

import httpx2
import pytest
from typesafe_sdk import TypeSafeClient

from triage import triage


def fake_jev(cause: str, confidence: float, retry: float, impact: float) -> TypeSafeClient:
    answers = {
        "cause": {"type": "choice", "choice": cause, "confidence": confidence, "probabilities": {cause: confidence}},
        "retry_will_succeed": {"type": "noul", "noul": retry},
        "impact": {"type": "score", "score": impact, "confidence": 1.0, "legend": {}, "probabilities": {}},
    }
    body = {"model": "jev-test", "answers": answers, "usage": {"input_tokens": 1, "output_tokens": 1}}
    return TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=body)))


@pytest.mark.parametrize(
    ("cause", "confidence", "retry", "impact", "attempt", "action"),
    [
        # A cause Jev cannot see goes to a human, however sure it is about that.
        ("unknown", 1.0, 0.9, 0.0, 1, "review"),
        # Just under the confidence floor goes to a human; at the floor, the automation acts.
        ("network", 0.59, 0.9, 0.0, 1, "review"),
        ("network", 0.6, 0.5, 0.0, 2, "retry"),
        # A transient failure below the retry threshold is not retried.
        ("network", 1.0, 0.49, 0.0, 1, "ticket"),
        # Out of attempts: no retry, and high impact pages on-call.
        ("resources", 1.0, 0.9, 1.5, 3, "page"),
        # Non-transient causes are never retried, even when Jev thinks a retry would work.
        ("credentials", 1.0, 0.9, 1.49, 1, "ticket"),
    ],
)
def test_triage_policy(cause: str, confidence: float, retry: float, impact: float, attempt: int, action: str) -> None:
    failure = {"pipeline": "orders_daily", "task": "load", "attempt": attempt, "error_log": "..."}

    assert triage(fake_jev(cause, confidence, retry, impact), failure).action == action
