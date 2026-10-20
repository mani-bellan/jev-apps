"""The Jev quick check: one call answers every question about a message."""

import asyncio
import os
import time

import httpx

from .extract import link_domains, redact, sender_kind

JEV_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.13.0"  # pinned: thresholds are tuned against one version's probabilities
PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000

SCAM_TYPES = {
    "kyc_account_block": "Bank, wallet, SIM, Aadhaar or PAN 'update KYC now or your account will be blocked or suspended'",
    "bill_disconnection": "Electricity, gas or water connection will be cut tonight unless you call someone or pay",
    "traffic_challan": "Traffic e-challan or fine to pay through a link or an app",
    "parcel_delivery": "Parcel held or delivery failed; pay a small fee or update your address through a link",
    "job_task": "Part-time or work-from-home job: like videos, rate products or complete tasks for money",
    "loan": "Instant or pre-approved loan that needs a fee, a link or an app install",
    "investment": "Stock tips, IPO, crypto or trading group promising high or guaranteed returns",
    "prize_lottery": "Lottery, KBC, lucky draw, gift or cashback the recipient supposedly won",
    "refund": "Income tax, electricity or other refund to claim through a link",
    "reward_points": "Bank or credit card reward points expiring; redeem through a link or an APK file",
    "relative_impersonation": "Someone posing as a relative, friend or official who urgently needs money",
    "otp_request": "Asks the recipient to share or forward an OTP or code they received",
    "free_scheme": "Free mobile recharge, data, cash, laptop or other benefit supposedly given by the Prime Minister, "
                   "a party, the government, TRAI or a company like Jio, often to celebrate an event; claim through a link",
    "other_scam": "A scam of another kind",
    "genuine_transaction": "A real OTP, debit or credit alert, booking, delivery update or bill from the actual company",
    "genuine_promotion": "A real marketing or offer message from a business",
    "personal": "An ordinary personal, family or work conversation",
    "unclear": "Too little information to tell what this is",
}
GENUINE_TYPES = {"genuine_transaction", "genuine_promotion", "personal"}

BRANDS = [
    "sbi", "hdfc_bank", "icici_bank", "axis_bank", "kotak_bank", "pnb", "bank_of_baroda", "other_bank",
    "paytm", "phonepe", "google_pay", "amazon", "flipkart", "india_post", "courier_company",
    "electricity_board", "income_tax_department", "uidai_aadhaar", "traffic_police", "airtel", "jio", "vi", "bsnl",
    "irctc", "other_government", "employer_or_recruiter", "other_company", "none",
]

QUESTIONS = {
    "is_scam": {
        "type": "noul",
        "instructions": "Is `message` a scam: an attempt to trick the recipient into giving money, OTPs, passwords, "
                        "card or bank details or documents, or into clicking a link, calling or messaging a fraudster, "
                        "or installing an app?",
        "criteria": {
            "true": "A fraud attempt. It typically impersonates a bank, government office, utility, courier, employer "
                    "or relative; threatens a block, fine or disconnection, or promises a prize, refund, job, loan or "
                    "easy profit; and asks the recipient to click a link, call or WhatsApp a personal number, share "
                    "an OTP, pay a fee or install an app.",
            "false": "A genuine message: an OTP or transaction alert the recipient triggered, a bill or delivery update "
                     "from the real company, a promotion from a real business, or a personal message. Genuine alerts "
                     "often add a toll-free number or official link for reporting fraud.",
        },
    },
    "scam_type": {
        "type": "choice",
        "instructions": "Which kind of message is `message`?",
        "criteria": SCAM_TYPES,
    },
    "asks_for": {
        "type": "choice",
        "instructions": "What is the main thing `message` asks the recipient to do?",
        "criteria": {
            "click_link": "Open a link",
            "call_number": "Call or WhatsApp a phone number",
            "share_details": "Share an OTP, password, card, bank or personal details",
            "pay_money": "Pay money or a fee, or approve a UPI request",
            "install_app": "Install an app or open an APK file",
            "reply": "Reply to the message",
            "nothing": "Nothing; it only informs",
        },
    },
    "pressure": {
        "type": "score",
        "instructions": "How much pressure does `message` put on the recipient to act immediately?",
        "criteria": [
            "None; purely informational",
            "Some urgency, or an attractive offer",
            "A threat, a deadline within hours, or a too-good-to-be-true reward",
        ],
    },
    "brand": {
        "type": "choice",
        "instructions": "Which organisation does `message` claim to be from or speak for?",
        "criteria": {b: b.replace("_", " ") for b in BRANDS},
    },
}

CONTEXT = ("A message received by a person in India by SMS or WhatsApp. OTPs, account numbers and phone numbers "
           "are partly masked with X for privacy; the masking is not part of the original message.")


def build_state(text: str, sender: str | None) -> dict:
    return {
        "context": CONTEXT,
        "sender": {"id": sender or "unknown", "kind": sender_kind(sender)},
        "message": redact(text),
        "link_domains": link_domains(text),
    }


class Jev:
    def __init__(self, model: str = DEFAULT_MODEL, concurrency: int = 8):
        key = os.environ.get("TYPESAFE_API_KEY")
        if not key:
            raise SystemExit("TYPESAFE_API_KEY is not set")
        self.model = model
        self.client = httpx.AsyncClient(headers={"Authorization": f"Bearer {key}"}, timeout=60)
        self.sem = asyncio.Semaphore(concurrency)

    async def check(self, text: str, sender: str | None = None) -> dict:
        """Ask every question about one message. Returns the state Jev saw, its answers, and usage."""
        return await self.ask(build_state(text, sender), QUESTIONS)

    async def ask(self, state: dict, questions: dict) -> dict:
        body = {"state": state, "model": self.model, "questions": questions}
        async with self.sem:
            for attempt in range(6):
                start = time.perf_counter()
                resp = await self.client.post(JEV_URL, json=body)
                if resp.status_code == 429 or resp.status_code >= 500:
                    await asyncio.sleep(float(resp.headers.get("retry-after", 0.5 * 2**attempt)))
                    continue
                resp.raise_for_status()
                data = resp.json()
                return {
                    "state": state,
                    "answers": data["answers"],
                    "model": data.get("model", self.model),
                    "latency_ms": round((time.perf_counter() - start) * 1000),
                    "input_tokens": data["usage"]["input_tokens"],
                }
            resp.raise_for_status()
            raise RuntimeError("unreachable")

    async def close(self) -> None:
        await self.client.aclose()
