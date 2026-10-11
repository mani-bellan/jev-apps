"""Routes a message to every agent it needs, using one Jev call."""

from dataclasses import dataclass

from typesafe_sdk import Noul, TypeSafeClient

from agents import Agent

RELEVANCE_THRESHOLD = 0.5
"""An agent is called when Jev's probability that the message needs it is at least this."""
URGENCY_THRESHOLD = 0.7
"""Messages at least this likely to be urgent are also escalated to a human."""


@dataclass
class RouteResult:
    relevance: dict[str, float]
    """Probability, per agent, that the message needs that agent."""
    urgency: float
    replies: dict[str, str]
    """Reply from each agent that was called, keyed by agent name."""
    escalate_reason: str | None
    """Why a human should take over, or None when the agents can handle it alone."""


class Router:
    def __init__(self, client: TypeSafeClient, agents: list[Agent]) -> None:
        self.client = client
        self.agents = agents

    def route(self, message: str) -> RouteResult:
        # One Jev call answers every question in parallel: one yes/no per agent, plus urgency.
        questions = {
            f"needs_{agent.name}": Noul(
                instructions=f"Resolving this message requires the {agent.name} team, which handles {agent.description}"
            )
            for agent in self.agents
        }
        questions["is_urgent"] = Noul(instructions="The message conveys urgency or time-sensitivity")
        nouls = self.client.system_one(message, questions).nouls

        relevance = {agent.name: nouls[f"needs_{agent.name}"].noul for agent in self.agents}
        urgency = nouls["is_urgent"].noul
        replies = {
            agent.name: agent.handle(self.client, message)
            for agent in self.agents
            if relevance[agent.name] >= RELEVANCE_THRESHOLD
        }

        if not replies:
            escalate_reason = "no agent matched the request"
        elif urgency >= URGENCY_THRESHOLD:
            escalate_reason = "the message is urgent"
        else:
            escalate_reason = None
        return RouteResult(relevance, urgency, replies, escalate_reason)
