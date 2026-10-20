"""Quick check, then the investigator for unsure messages with links."""

import datetime as dt

from . import policy
from .extract import links
from .investigate import FINAL_QUESTION, INVESTIGATION_NOTE, Investigator
from .jev import Jev


async def assess(jev: Jev, inv: Investigator | None, text: str, sender: str | None = None,
                 as_of: dt.date | None = None, force: bool = False) -> dict:
    """Returns the quick result, the decision, and (when investigated) the evidence and the final P(scam).
    `decision` is the final one; `quick` keeps the decision before investigating."""
    res = await jev.check(text, sender)
    quick = policy.decide(res["answers"])
    out = {**res, "quick": quick, "decision": quick, "investigation": None}
    if inv is None or not links(text) or not (force or quick["verdict"] == "unsure"):
        return out
    evidence = await inv.investigate(text, quick["brand"], as_of)
    state = {**res["state"], "investigation": {"note": INVESTIGATION_NOTE, "links": evidence}}
    final = await jev.ask(state, FINAL_QUESTION)
    out.update(investigation=evidence, decision=policy.decide_final(quick, final["answers"]["is_scam"]["noul"]),
               input_tokens=res["input_tokens"] + final["input_tokens"],
               latency_ms=res["latency_ms"] + final["latency_ms"])
    return out
