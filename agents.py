"""Specialist agents. The router calls an agent when Jev decides the message needs it."""

from dataclasses import dataclass

from typesafe_sdk import Choice, TypeSafeClient


@dataclass(frozen=True)
class Agent:
    name: str
    description: str
    """What this agent handles. The router shows this to Jev to decide whether to call the agent."""
    actions: dict[str, tuple[str, str]]
    """Action label -> (when to pick it, reply to send)."""

    def handle(self, client: TypeSafeClient, message: str) -> str:
        """Ask Jev which action fits the message, then run it."""
        response = client.system_one(
            message,
            {
                "action": Choice(
                    instructions=f"Which {self.name} action best handles this customer's request?",
                    criteria={label: when for label, (when, _) in self.actions.items()},
                )
            },
        )
        return self.actions[response.choices["action"].choice][1]


AGENTS = [
    Agent(
        name="billing",
        description="charges, refunds, invoices, or payment methods",
        actions={
            "refund": (
                "Wants money back or reports a duplicate or wrong charge",
                "I've opened a refund review. Duplicate charges are usually reversed within 5 business days.",
            ),
            "invoice": (
                "Needs an invoice, receipt, or explanation of a charge",
                "You can download every invoice from Settings → Billing → Invoices.",
            ),
            "payment_method": (
                "Wants to update a card or reports a failed payment",
                "Update your card under Settings → Billing → Payment method, then retry the payment.",
            ),
        },
    ),
    Agent(
        name="technical",
        description="bugs, errors, outages, or integration problems",
        actions={
            "integration": (
                "A third-party integration or API connection fails",
                "Please reconnect the integration from Settings → Integrations and send us the error code if it fails again.",
            ),
            "bug": (
                "Part of the product behaves incorrectly or shows an error",
                "Thanks for the report. I've logged a bug; a screenshot and the steps to reproduce will help us fix it faster.",
            ),
            "outage": (
                "The whole service is down or unreachable",
                "Check status.example.com for live incident updates. We'll email you when it's resolved.",
            ),
        },
    ),
    Agent(
        name="account",
        description="login, passwords, profile changes, or closing an account",
        actions={
            "login": (
                "Cannot sign in or needs a password reset",
                "I've sent a password reset link to the email on your account.",
            ),
            "profile": (
                "Wants to change their name, email, or other profile details",
                "You can change your profile details under Settings → Profile.",
            ),
            "close_account": (
                "Wants to delete or close their account",
                "I've started account closure. You'll get a confirmation email before anything is deleted.",
            ),
        },
    ),
    Agent(
        name="sales",
        description="pricing, plans, upgrades, or buying more seats",
        actions={
            "pricing": (
                "Asks what plans cost or how they differ",
                "Our plans are listed at example.com/pricing. Annual billing saves 20%.",
            ),
            "upgrade": (
                "Wants to upgrade their plan or add seats",
                "You can upgrade or add seats instantly under Settings → Plan.",
            ),
            "demo": (
                "Wants a demo, a trial, or to talk to sales",
                "I've asked our sales team to reach out and book a demo with you.",
            ),
        },
    ),
]
