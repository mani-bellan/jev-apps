"""Command-line entry point.

    uv run main.py "I was charged twice and now I can't log in"
    uv run main.py            # interactive mode
"""

import sys

from typesafe_sdk import TypeSafeClient, TypeSafeError

from agents import AGENTS
from router import RELEVANCE_THRESHOLD, Router


def show(router: Router, message: str) -> None:
    result = router.route(message)
    scores = ", ".join(
        f"{name} {p:.2f}{' ✓' if p >= RELEVANCE_THRESHOLD else ''}" for name, p in result.relevance.items()
    )
    print(f"Routing: {scores} | urgency {result.urgency:.2f}")
    for name, reply in result.replies.items():
        print(f"[{name} agent] {reply}")
    if result.escalate_reason:
        print(f"[human] Escalated to a human because {result.escalate_reason}.")


def main() -> None:
    try:
        client = TypeSafeClient()  # reads TYPESAFE_API_KEY from the environment
    except TypeSafeError as error:
        sys.exit(f"Could not create the Jev client: {error}\nSet TYPESAFE_API_KEY (get one at https://console.typesafe.ai/keys).")

    with client:
        router = Router(client, AGENTS)
        if len(sys.argv) > 1:
            show(router, " ".join(sys.argv[1:]))
            return
        print("Type a customer message (Ctrl+D to quit).")
        while True:
            try:
                message = input("> ").strip()
            except EOFError:
                break
            if message:
                show(router, message)


if __name__ == "__main__":
    main()
