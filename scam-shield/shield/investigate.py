"""M2 investigator: for messages the quick check is unsure about, check every link and ask Jev again with the
evidence. Links are fetched from wherever this runs (an orb or a server), never from the recipient's phone."""

import asyncio
import datetime as dt
import re
from html import unescape

import httpx

from .extract import host, links, registered_domain

OFFICIAL = {  # registered domains each organisation actually uses
    "sbi": {"sbi.co.in", "onlinesbi.sbi", "sbicard.com", "yonobusiness.sbi"},
    "hdfc_bank": {"hdfcbank.com", "hdfcbk.io"},
    "icici_bank": {"icicibank.com", "icicibank.co.in"},
    "axis_bank": {"axisbank.com", "axis.bank.in"},
    "kotak_bank": {"kotak.com", "kotak.bank.in"},
    "pnb": {"pnbindia.in"},
    "bank_of_baroda": {"bankofbaroda.in", "bankofbaroda.com"},
    "paytm": {"paytm.com", "paytmbank.com"},
    "phonepe": {"phonepe.com"},
    "google_pay": {"google.com", "g.co"},
    "amazon": {"amazon.in", "amazon.com", "amzn.in", "amzn.to", "amzn.eu"},
    "flipkart": {"flipkart.com", "fkrt.it"},
    "india_post": {"indiapost.gov.in", "ippbonline.com"},
    "courier_company": {"fedex.com", "dhl.com", "bluedart.com", "delhivery.com", "dtdc.com", "dtdc.in",
                        "ecomexpress.in", "xpressbees.com", "shadowfax.in", "ekartlogistics.com"},
    "electricity_board": {"tatapower.com", "tatapower-ddl.com", "adanielectricity.com", "bsesdelhi.com",
                          "mahadiscom.in", "torrentpower.com", "cesc.co.in", "bescom.co.in"},
    "airtel": {"airtel.in", "airtel.com"},
    "jio": {"jio.com"},
    "vi": {"myvi.in", "vodafoneidea.com"},
    "bsnl": {"bsnl.co.in", "bsnl.in"},
    "irctc": {"irctc.co.in"},
    "other_company": {"microsoft.com", "aka.ms", "apple.com", "swiggy.com", "zomato.com", "myntra.com"},
}
GROUPS = {"courier_company", "electricity_board", "other_company"}  # entries that cover several companies
OFFICIAL_SUFFIXES = (".gov.in", ".nic.in", ".bank.in")  # registries restricted to government bodies and banks
OPEN_PLATFORMS = {  # anyone can make a link on these, so the domain says nothing about who sent it
    "bit.ly", "tinyurl.com", "goo.gl", "rb.gy", "is.gd", "cutt.ly", "shorturl.at", "s.id", "t.ly", "surl.li",
    "lnk.ink", "did.li", "lihi.cc", "wa.me", "t.me", "forms.gle", "sites.google.com", "wixsite.com",
    "blogspot.com", "linktr.ee", "github.io", "netlify.app", "vercel.app", "pages.dev", "web.app", "firebaseapp.com",
}


def ownership(hostname: str, claimed_brand: str) -> str:
    reg = registered_domain(hostname)
    if reg in OPEN_PLATFORMS or hostname in OPEN_PLATFORMS:
        return "a link shortener or open platform that anyone can use"
    if reg in OFFICIAL.get(claimed_brand, set()):
        name = "the company" if claimed_brand in GROUPS else claimed_brand.replace("_", " ")
        return f"{reg}, an official domain of {name} the message claims to be from"
    if hostname.endswith(OFFICIAL_SUFFIXES):
        return "a domain in a registry reserved for Indian government bodies or banks (.gov.in, .nic.in, .bank.in)"
    owner = next((b for b, domains in OFFICIAL.items() if reg in domains), None)
    if owner:
        name = "a known company" if owner in GROUPS else owner.replace("_", " ")
        return f"{reg}, an official domain of {name}, but not of the organisation the message claims to be from"
    return "not a known official domain of any organisation"


def page_summary(html: str) -> dict:
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    inputs = {m.lower() for m in re.findall(
        r"(?i)<input[^>]*(?:type|name|placeholder|id)=[\"']?([^\"'\s>]*(?:password|card|cvv|otp|pin|aadhaar|pan|"
        r"account|ifsc|upi|mobile|phone|expiry)[^\"'\s>]*)", html)}
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = unescape(re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", text))).strip()
    return {"title": unescape(title.group(1).strip())[:200] if title else "", "text": text[:1500],
            "form_fields": sorted(inputs)[:15]}


class Investigator:
    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"},
            timeout=httpx.Timeout(8.0), follow_redirects=True, verify=False,  # phishing sites often have bad certs
        )
        self.rdap_cache: dict[str, str | None] = {}

    async def registration_date(self, domain: str) -> str | None:
        if domain not in self.rdap_cache:
            date = None
            try:
                resp = await self.client.get(f"https://rdap.org/domain/{domain}", timeout=10)
                if resp.status_code == 200:
                    date = next((e["eventDate"][:10] for e in resp.json().get("events", [])
                                 if e.get("eventAction") == "registration"), None)
            except (httpx.HTTPError, ValueError):
                pass
            self.rdap_cache[domain] = date
        return self.rdap_cache[domain]

    async def fetch(self, url: str) -> dict:
        out: dict = {}
        try:
            async with self.client.stream("GET", url) as resp:
                ctype = resp.headers.get("content-type", "").split(";")[0].strip()
                out.update(final_url=str(resp.url), status=resp.status_code, redirects=len(resp.history))
                if "android" in ctype or str(resp.url).lower().split("?")[0].endswith(".apk"):
                    out["serves_app_file"] = True  # never download the app itself
                elif "html" in ctype or "text" in ctype:
                    body = b""
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                        if len(body) > 300_000:
                            break
                    out["page"] = page_summary(body.decode(resp.encoding or "utf-8", "replace"))
        except Exception as e:  # dead, blocked or malformed links are common and are evidence too
            out["error"] = type(e).__name__
        return out

    async def check_link(self, url: str, brand: str, as_of: dt.date) -> dict:
        fetched = await self.fetch(url)
        final_host = host(fetched.get("final_url", url))
        evidence = {"link": url, "lands_on": final_host, "domain_owner": ownership(final_host, brand)}
        if final_host != host(url):
            evidence["redirected_from"] = f"{host(url)} ({ownership(host(url), brand)})"
        reg = await self.registration_date(registered_domain(final_host))
        if reg:
            days = (as_of - dt.date.fromisoformat(reg)).days
            evidence["domain_registered"] = (f"{reg}, {days} days before the message was received" if days >= 0
                                             else f"{reg}, after the message was received (re-registered later)")
        else:
            evidence["domain_registered"] = "no registration record found (expired, never registered, or not published)"
        if "error" in fetched:
            evidence["fetch"] = f"could not be opened ({fetched['error']})"
        elif fetched.get("serves_app_file"):
            evidence["fetch"] = "downloads an Android app file (APK) instead of a web page"
        elif "page" in fetched:
            evidence["fetch"] = f"HTTP {fetched['status']} after {fetched['redirects']} redirects"
            evidence["page"] = fetched["page"]
        else:
            evidence["fetch"] = f"HTTP {fetched['status']}, not a web page"
        return evidence

    async def investigate(self, text: str, brand: str, as_of: dt.date | None = None) -> list[dict]:
        as_of = as_of or dt.date.today()
        return list(await asyncio.gather(*(self.check_link(u, brand, as_of) for u in links(text)[:3])))

    async def close(self) -> None:
        await self.client.aclose()


FINAL_QUESTION = {
    "is_scam": {
        "type": "noul",
        "instructions": "Considering `message` together with `investigation`, the results of opening each link in "
                        "the message, is `message` a scam?",
        "criteria": {
            "true": "A fraud attempt. Strong signs: a link on a look-alike or recently registered domain, a link "
                    "shortener hiding an unofficial site, a page asking for card details, OTP, password, PIN or "
                    "a small fee, or a link that downloads an app file, while the message claims to be from a bank, "
                    "government office, utility or courier.",
            "false": "A genuine message. Strong signs: every link lands on an official domain of the organisation "
                     "the message claims to be from, or on a .gov.in, .nic.in or .bank.in domain, and the request "
                     "matches what that organisation normally sends.",
        },
    },
}
INVESTIGATION_NOTE = ("Links were opened from a sandbox, not the recipient's phone. Scam sites are often taken down "
                      "within days, so a link that cannot be opened today is weak evidence either way; for older "
                      "messages, judge mostly by domain ownership and registration date.")
