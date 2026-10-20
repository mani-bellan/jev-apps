"""Plain-code steps before Jev: mask private numbers, pull out link domains, describe the sender."""

import re

_OTP_AFTER = re.compile(
    r"(?i)(\b(?:otp|one[- ]time password|verification code|code|pin|password|passcode)\b[^0-9\n]{0,25})(\d{4,8})\b"
)
_OTP_BEFORE = re.compile(r"(?i)(?<!\d)(\d{4,8})(\s+is\s+(?:your|the)\s+(?:otp|one[- ]time password|verification code|code))")
_AADHAAR = re.compile(r"(?<!\d)\d{4}[ -]\d{4}[ -](\d{4})(?!\d)")
_MOBILE = re.compile(r"(?<![\d\w+])(\+91[\s-]?|0)?([6-9](?:[\s-]?\d){9})(?!\d)")
_LONG_NUMBER = re.compile(r"(?<![\d\w])(?!1800|1860)\d{9,18}(?!\d)")


def _mask_mobile(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    return digits[:2] + "XXXXXX" + digits[-2:]


def redact(text: str) -> str:
    """Mask OTPs, account/card/Aadhaar numbers and mobile numbers, keeping their shape.

    Mobile numbers keep their first and last two digits (98XXXXXX21) so "this asks you to call a personal
    number" survives; toll-free 1800/1860 numbers are left alone because they are a signal of a real company.
    """
    text = _OTP_AFTER.sub(lambda m: m.group(1) + "<OTP>", text)
    text = _OTP_BEFORE.sub(lambda m: "<OTP>" + m.group(2), text)
    text = _AADHAAR.sub(lambda m: "XXXX XXXX " + m.group(1), text)
    text = _MOBILE.sub(lambda m: (m.group(1) or "") + _mask_mobile(m.group(2)), text)
    return _LONG_NUMBER.sub(lambda m: "X" * (len(m.group(0)) - 4) + m.group(0)[-4:], text)


_TLDS = (r"com|in|net|org|co|io|ly|me|info|xyz|top|site|online|link|app|shop|live|club|cc|tk|vip|icu|buzz|cfd|sbs|"
         r"gl|gd|to|li|ink|gy|ws|pw|ru|cn|tv|us|biz|pro|store|fun|website|space|tech|ai|im|la|bz|mobi|asia|win|"
         r"click|lol|rest|bond|today|world|life|help|support|services|ms|sbi|bank|gov")
_URL = re.compile(
    rf"(?i)\bhttps?://[^\s<>\"']+|(?<![@\w.])(?:www\.)?(?:[a-z0-9-]+\.)+(?:{_TLDS})\b(?:/[^\s<>\"']*)?"
)


def links(text: str) -> list[str]:
    """Every link in the text as a fetchable URL (https:// added when the message leaves it out)."""
    urls = []
    for url in _URL.findall(text):
        url = url.rstrip(".,)\"'")
        if not re.match(r"(?i)https?://", url):
            url = "https://" + url
        if url not in urls:
            urls.append(url)
    return urls


def host(url: str) -> str:
    return re.sub(r"(?i)^https?://", "", url).split("/")[0].split("?")[0].split(":")[0].lower().removeprefix("www.")


def link_domains(text: str) -> list[str]:
    return list(dict.fromkeys(host(u) for u in links(text)))


_TWO_PART_SUFFIXES = {"co.in", "gov.in", "nic.in", "org.in", "net.in", "ac.in", "bank.in", "firm.in", "gen.in",
                      "ind.in", "edu.in", "res.in", "co.uk", "org.uk", "com.au", "co.jp", "com.br", "com.pk"}


def registered_domain(hostname: str) -> str:
    """The part someone registers: login.sbi.co.in -> sbi.co.in, a.b.example.com -> example.com."""
    parts = hostname.split(".")
    n = 3 if ".".join(parts[-2:]) in _TWO_PART_SUFFIXES else 2
    return ".".join(parts[-n:])


_HEADER = re.compile(r"^[A-Z]{2}-[A-Z0-9]{3,9}(?:-([PSTG]))?$", re.I)
_HEADER_KINDS = {"P": "promotional", "S": "service", "T": "transactional", "G": "government"}


def sender_kind(sender: str | None) -> str:
    if not sender:
        return "not provided"
    s = sender.strip()
    if m := _HEADER.match(s):
        kind = _HEADER_KINDS.get((m.group(1) or "").upper())
        return f"registered business sender ID ({kind})" if kind else "registered business sender ID"
    if re.fullmatch(r"\+?[\d\s-]{10,15}", s):
        return "a personal or unregistered phone number"
    return "a named contact or app, not a registered sender ID"


_HINDI_WORDS = set(
    "hai hain aap aapka aapki aapke apna karein kare karo kijiye nahi nahin gaya gayi hoga hogi jayega jayegi "
    "turant abhi mein mai yeh ye woh wo kya kyun kaise bhai paise rupaye milega mila jaldi warna varna "
    "tum tu tera tumhara mera meri hum ho raha rahi ka ki ke se liye karne aur bhi aaj kal raat ghar baje "
    "bhejo bhejna diya kiya karna hua".split()
)


def detect_lang(text: str) -> str:
    """en, hinglish (Hindi in Roman script) or hi (Devanagari). A heuristic used only when data has no lang."""
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    words = set(re.findall(r"[a-z]+", text.lower()))
    return "hinglish" if len(words & _HINDI_WORDS) >= 2 else "en"
