"""Labeled message sets: your own JSONL files, or a named public dataset downloaded on first use.

A record is {"text", "label": scam | spam | legit, "sender"?, "scam_type"?, "lang"?, "source"?}.
"spam" means unwanted but not fraudulent (promotions); it counts toward neither catch rate nor false alarms.
"""

import csv
import io
import json
import random
import zipfile
from pathlib import Path

import httpx

from .extract import detect_lang

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"

PUBLIC = {
    # Mishra & Soni (2022), CC BY 4.0. Mostly older UK and global SMS, so it is a sanity check, not an India test.
    "mendeley": "https://data.mendeley.com/public-files/datasets/f45bkkt8pr/files/"
                "edb361de-918d-469f-9106-e84823830665/file_downloaded",
    # bolewara/hinglish-scam-text-dataset, CC BY 4.0. Only its 63 hand-written Hinglish rows are used; the rest is
    # the UCI SMS Spam Collection, which is already inside the Mendeley set.
    "hinglish-hf": "https://huggingface.co/datasets/bolewara/hinglish-scam-text-dataset/resolve/main/data.json",
}
LABELS = {"scam", "spam", "legit"}


def _download(name: str) -> bytes:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name} ...")
        resp = httpx.get(PUBLIC[name], follow_redirects=True, timeout=120)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path.read_bytes()


def _mendeley() -> list[dict]:
    raw = zipfile.ZipFile(io.BytesIO(_download("mendeley"))).read("Dataset_5971.csv").decode("utf-8", "replace")
    labels = {"ham": "legit", "spam": "spam", "smishing": "scam"}
    return [{"text": r["TEXT"].strip(), "label": labels[r["LABEL"].strip().lower()], "lang": "en", "source": "mendeley"}
            for r in csv.DictReader(io.StringIO(raw))]


def _hinglish_hf() -> list[dict]:
    rows = json.loads(_download("hinglish-hf"))["rows"]
    return [{"text": r["text"], "label": "scam" if r["label"] else "legit", "lang": "hinglish", "source": "hinglish-hf"}
            for r in rows if detect_lang(r["text"]) == "hinglish"]


def load(name_or_path: str, sample: int | None = None, seed: int = 7) -> list[dict]:
    if name_or_path == "mendeley":
        records = _mendeley()
    elif name_or_path == "hinglish-hf":
        records = _hinglish_hf()
    else:
        path = Path(name_or_path)
        if not path.exists():
            raise SystemExit(f"{name_or_path}: no such file (public sets: {', '.join(PUBLIC)})")
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for i, r in enumerate(records):
        if r.get("label") not in LABELS:
            raise SystemExit(f"{name_or_path} record {i + 1}: label must be one of {sorted(LABELS)}")
        r.setdefault("id", f"{Path(name_or_path).stem}-{i + 1}")
        r.setdefault("lang", detect_lang(r["text"]))
    if sample and sample < len(records):
        # Stratified so a small sample still has every label.
        rng = random.Random(seed)
        by_label = {lab: [r for r in records if r["label"] == lab] for lab in LABELS}
        picked = []
        for lab, rs in by_label.items():
            picked += rng.sample(rs, min(len(rs), round(sample * len(rs) / len(records))))
        records = picked
    return records
