"""shield serve: a one-page demo. Paste a message, get the verdict and the evidence. Standard library only."""

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .investigate import Investigator
from .jev import Jev
from .pipeline import assess

PAGE = (Path(__file__).parent / "web.html").read_bytes()


async def check(text: str, sender: str | None, model: str) -> dict:
    jev, inv = Jev(model), Investigator()
    try:
        res = await assess(jev, inv, text, sender)
    finally:
        await jev.close()
        await inv.close()
    return {"decision": res["decision"], "investigation": res["investigation"], "model": res["model"],
            "latency_ms": res["latency_ms"], "input_tokens": res["input_tokens"],
            "masked_message": res["state"]["message"], "sender_kind": res["state"]["sender"]["kind"]}


def serve(port: int, model: str) -> None:
    class Handler(BaseHTTPRequestHandler):
        def send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send(200, PAGE, "text/html; charset=utf-8")
            else:
                self.send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path != "/api/check":
                return self.send(404, b"not found", "text/plain")
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                text = (req.get("text") or "").strip()[:4000]
                if not text:
                    return self.send(400, b'{"error": "Paste a message first."}', "application/json")
                result = asyncio.run(check(text, (req.get("sender") or "").strip() or None, model))
                self.send(200, json.dumps(result, ensure_ascii=False).encode(), "application/json")
            except Exception as e:  # show the reason in the page instead of a broken request
                self.send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")

        def log_message(self, fmt, *args):  # keep message text out of server logs
            pass

    print(f"Scam Shield demo on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
