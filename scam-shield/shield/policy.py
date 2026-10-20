"""Turns Jev's answers into a verdict and a one-line explanation. The thresholds are business decisions:
tune them on your own labeled data, never on the held-out set."""

from .jev import GENUINE_TYPES

SCAM_AT = 0.8  # P(scam) at or above this: warn
SAFE_AT = 0.2  # P(scam) at or below this: pass. In between: unsure (the investigator's job from M2)

WHY = {
    "kyc_account_block": "Banks and telecoms don't block accounts over SMS links; KYC is updated in the official app or at a branch.",
    "bill_disconnection": "Electricity boards don't ask you to call a personal mobile number to avoid disconnection.",
    "traffic_challan": "Fake challans use look-alike links or APK files; check challans only on echallan.parivahan.gov.in.",
    "parcel_delivery": "Couriers don't collect fees or card details through SMS links.",
    "job_task": "Paid 'tasks' that later ask you to deposit money are a common scam.",
    "loan": "Genuine lenders don't charge an upfront fee to release a loan.",
    "investment": "Guaranteed high returns and private tip groups are hallmarks of investment fraud.",
    "prize_lottery": "You can't win a lottery or lucky draw you never entered.",
    "refund": "Tax refunds are credited to your bank account automatically; nobody claims them through a link.",
    "reward_points": "Banks don't send links or APK files to redeem reward points.",
    "relative_impersonation": "Call the person on the number you already have before sending any money.",
    "otp_request": "Never share an OTP; no genuine person or company will ask for it.",
    "free_scheme": "No government, party or telecom company hands out free recharges, cash or laptops through forwarded links.",
}
ASKS = {
    "click_link": "asks you to open a link",
    "call_number": "asks you to call a number",
    "share_details": "asks for your details",
    "pay_money": "asks you to pay",
    "install_app": "asks you to install an app",
    "reply": "asks you to reply",
    "nothing": "asks for nothing",
}
DO = {
    "scam": "Don't click, call, pay or reply. Report it at 1930 or cybercrime.gov.in.",
    "unsure": "Don't click links or call numbers in it. Check directly in the company's official app or website.",
    "safe": "No action needed.",
}


def decide(answers: dict) -> dict:
    p = answers["is_scam"]["noul"]
    kind = answers["scam_type"]["choice"]
    asks = answers["asks_for"]["choice"]
    verdict = "scam" if p >= SCAM_AT else "safe" if p <= SAFE_AT else "unsure"

    if verdict == "safe":
        why = "Looks like " + {"genuine_transaction": "a genuine alert or transaction message",
                               "genuine_promotion": "a genuine promotion",
                               "personal": "an ordinary personal message"}.get(kind, "a genuine message") + "."
    elif kind in WHY:
        why = WHY[kind]
    elif kind in GENUINE_TYPES:
        why = f"Reads like a genuine message, but it {ASKS[asks]} and has some signs of fraud."
    else:
        why = f"It {ASKS[asks]} and shows common signs of fraud."
    return {"verdict": verdict, "p_scam": p, "scam_type": kind, "asks_for": asks,
            "pressure": answers["pressure"]["score"], "brand": answers["brand"]["choice"],
            "why": why, "do": DO[verdict]}


def decide_final(quick: dict, p: float) -> dict:
    """Verdict after the investigator: same thresholds, applied to the P(scam) that saw the link evidence."""
    verdict = "scam" if p >= SCAM_AT else "safe" if p <= SAFE_AT else "unsure"
    why = {"safe": "Checking its links found no signs of fraud.",
           "scam": "Checking its links found signs of fraud. " + quick["why"]}.get(verdict, quick["why"])
    return {**quick, "verdict": verdict, "p_scam": p, "p_quick": quick["p_scam"], "why": why, "do": DO[verdict]}
