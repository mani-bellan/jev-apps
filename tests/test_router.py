"""Router tests against a fake Jev API, so they run without an API key or network."""

import json

import httpx2
from typesafe_sdk import TypeSafeClient

from agents import AGENTS
from router import Router

# The action each agent's Jev call would pick, keyed by agent name.
ACTIONS = {"billing": "refund", "technical": "integration", "account": "login", "sales": "demo"}


def fake_jev(probabilities: dict[str, float], calls: list[str]) -> TypeSafeClient:
    """A client whose API answers routing nouls from `probabilities` and records which agents ran."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        questions = json.loads(request.content)["questions"]
        if "action" in questions:  # an agent's own call
            labels = questions["action"]["criteria"]
            agent = next(name for name, action in ACTIONS.items() if action in labels)
            calls.append(agent)
            answers = {
                "action": {"type": "choice", "choice": ACTIONS[agent], "confidence": 0.9, "probabilities": {ACTIONS[agent]: 1.0}}
            }
        else:  # the router's call
            answers = {key: {"type": "noul", "noul": probabilities[key]} for key in questions}
        return httpx2.Response(200, json={"model": "jev-test", "answers": answers, "usage": {"input_tokens": 1, "output_tokens": 1}})

    return TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(handler))


def test_calls_every_agent_at_or_above_the_threshold() -> None:
    calls: list[str] = []
    client = fake_jev(
        {"needs_billing": 0.92, "needs_technical": 0.5, "needs_account": 0.49, "needs_sales": 0.05, "is_urgent": 0.2},
        calls,
    )

    result = Router(client, AGENTS).route("I was double charged and the Stripe integration fails")

    assert sorted(calls) == ["billing", "technical"]
    assert result.replies == {
        "billing": AGENTS[0].actions["refund"][1],
        "technical": AGENTS[1].actions["integration"][1],
    }
    assert result.escalate_reason is None


def test_urgent_message_is_handled_and_escalated() -> None:
    calls: list[str] = []
    client = fake_jev(
        {"needs_billing": 0.1, "needs_technical": 0.1, "needs_account": 0.95, "needs_sales": 0.1, "is_urgent": 0.7},
        calls,
    )

    result = Router(client, AGENTS).route("I'm locked out and my demo is in 10 minutes!")

    assert calls == ["account"]
    assert result.escalate_reason == "the message is urgent"


def test_unmatched_message_goes_to_a_human_without_calling_agents() -> None:
    calls: list[str] = []
    client = fake_jev(
        {"needs_billing": 0.2, "needs_technical": 0.1, "needs_account": 0.3, "needs_sales": 0.4, "is_urgent": 0.1},
        calls,
    )

    result = Router(client, AGENTS).route("What's your favourite colour?")

    assert calls == []
    assert result.replies == {}
    assert result.escalate_reason == "no agent matched the request"
