"""One client for any decision model that serves the /v1/systemone API: Jev (hosted by TypeSafe) or Strands Decider
(open weights, served by `strands-decider serve`). Both take the same request and return the same answers."""

import asyncio
import os
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Backend:
    name: str
    url: str
    model: str
    key_env: str | None  # environment variable holding the API key, if the server needs one
    usd_per_million_input_tokens: float | None  # None: you pay for the hardware instead
    describe_options: bool  # give each option a one-line description, or bare labels (see questions.py)


BACKENDS = {
    "jev": Backend("jev", "https://api.typesafe.ai/v1/systemone", "jev-1.13.0", "TYPESAFE_API_KEY", 0.042, True),
    "strands": Backend("strands", os.environ.get("STRANDS_URL", "http://127.0.0.1:8000/v1/systemone"),
                       "strands-decider-2B-qwen3.5-v1-2610", None, None, False),
}


class Decider:
    def __init__(self, backend: str, concurrency: int = 8, timeout: float = 600):
        self.backend = BACKENDS[backend]
        headers = {}
        if self.backend.key_env:
            key = os.environ.get(self.backend.key_env)
            if not key:
                raise SystemExit(f"{self.backend.key_env} is not set")
            headers["Authorization"] = f"Bearer {key}"
        self.client = httpx.AsyncClient(headers=headers, timeout=timeout)
        self.sem = asyncio.Semaphore(concurrency)

    async def ask(self, state: dict, questions: dict) -> dict:
        """Returns the answers, the model that gave them, input tokens, and the latency of the successful call."""
        body = {"state": state, "model": self.backend.model, "questions": questions}
        async with self.sem:
            for attempt in range(8):
                start = time.perf_counter()
                try:
                    resp = await self.client.post(self.backend.url, json=body)
                except httpx.TransportError:
                    await asyncio.sleep(2 ** min(attempt, 5))
                    continue
                if resp.status_code == 429 or resp.status_code >= 500:
                    await asyncio.sleep(float(resp.headers.get("retry-after", 2 ** min(attempt, 5))))
                    continue
                resp.raise_for_status()
                data = resp.json()
                return {"answers": data["answers"], "model": data.get("model", self.backend.model),
                        "input_tokens": data.get("usage", {}).get("input_tokens", 0),
                        "latency_ms": round((time.perf_counter() - start) * 1000)}
            raise RuntimeError(f"{self.backend.name}: no answer after 8 attempts")

    async def close(self) -> None:
        await self.client.aclose()
