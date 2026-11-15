"""Builds the labeled splits from the public US Consumer Complaint Database (CFPB, public domain).

The CFPB's own downloads stopped including complaint text in 2026, so this reads a July 2026 Parquet copy of the
full database, made from the CFPB's CSV, that still has it. Every record keeps the label the consumer chose when
filing (product and issue); nobody relabeled anything.

Selection, all fixed by a seed so a rebuild gives the same files:
- complaints received in 2025 that have text, 200 to 2,500 characters long;
- text that appears exactly once in the database (form letters filed many times are dropped);
- an issue that makes up at least 2% of its product's 2025 complaints, so every issue has enough examples;
- per product, a hash-ordered sample: 10 dev, 40 tune, 70 held-out, then up to 2,000 more as classifier training data.
Products are sampled equally on purpose; in the raw data three in four complaints are about credit reports.
"""

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from .questions import DATA, PRODUCTS

PARQUET_URL = "https://huggingface.co/datasets/Mouwiya/cfpb-consumer-complaints/resolve/main/data/complaints-{:05d}.parquet"
PARQUET_FILES = 67
SPLITS = {"dev": 10, "tune": 40, "heldout": 70}
TRAIN_LARGE = 2000
MIN_ISSUE_SHARE = 0.02
SEED = "autolabel-1"


def download(cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=300) as client:
        for i in range(PARQUET_FILES):
            path = cache / f"complaints-{i:05d}.parquet"
            if not path.exists():
                print(f"downloading {path.name} ({i + 1}/{PARQUET_FILES})")
                resp = client.get(PARQUET_URL.format(i))
                resp.raise_for_status()
                path.write_bytes(resp.content)
    return cache


def build(parquet_dir: Path | None = None) -> None:
    import duckdb  # only needed here: uv run --group data autolabel build-data

    parquet_dir = parquet_dir or download(DATA / "cache")
    db = duckdb.connect()
    db.sql(f"""create view c2025 as select complaint_id id, cast(date_received as date) date, product, issue, sub_issue,
                 trim(consumer_complaint_narrative) text
               from read_parquet('{parquet_dir}/*.parquet')
               where date_received >= '2025-01-01' and date_received < '2026-01-01'
                 and length(trim(consumer_complaint_narrative)) > 0""")

    # Issues (and their most common sub-issues, as descriptions) from all 2025 complaints with text.
    counts = db.sql("select product, issue, sub_issue, count(*) from c2025 group by all").fetchall()
    issue_n, sub_n = defaultdict(Counter), defaultdict(Counter)
    for product, issue, sub, n in counts:
        issue_n[product][issue] += n
        if sub:
            sub_n[(product, issue)][sub] += n
    assert set(issue_n) == set(PRODUCTS), set(issue_n) ^ set(PRODUCTS)
    tax = {}
    for product in PRODUCTS:
        total = sum(issue_n[product].values())
        tax[product] = {issue: "; ".join(s for s, _ in sub_n[(product, issue)].most_common(4)) or issue
                        for issue, n in issue_n[product].most_common() if n / total >= MIN_ISSUE_SHARE}

    candidates = db.sql("""select id, product, issue from c2025
                           where length(text) between 200 and 2500
                             and text in (select text from c2025 group by text having count(*) = 1)""").fetchall()
    by_product = defaultdict(list)
    for cid, product, issue in candidates:
        if issue in tax[product]:
            by_product[product].append(cid)

    chosen = {}
    n_eval = sum(SPLITS.values())
    for product, ids in by_product.items():
        ids.sort(key=lambda cid: hashlib.sha256(f"{SEED}:{cid}".encode()).hexdigest())
        start = 0
        for split, n in SPLITS.items():
            chosen.update({cid: split for cid in ids[start:start + n]})
            start += n
        chosen.update({cid: "train_large" for cid in ids[n_eval:n_eval + TRAIN_LARGE]})

    db.sql("create temp table pick(id varchar, split varchar)")
    db.executemany("insert into pick values (?, ?)", list(chosen.items()))
    rows = db.sql("""select p.split, c.id, c.date, c.product, c.issue, c.sub_issue, c.text
                     from c2025 c join pick p using (id) order by c.product, c.id""").fetchall()
    out = defaultdict(list)
    for split, cid, date, product, issue, sub, text in rows:
        out[split].append({"id": cid, "date": str(date), "product": product, "issue": issue, "sub_issue": sub,
                           "text": text})
    DATA.mkdir(exist_ok=True)
    (DATA / "taxonomy.json").write_text(json.dumps(tax, indent=2) + "\n")
    for split, records in out.items():
        (DATA / f"{split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        print(f"{split:12} {len(records):6} complaints")
    print(f"taxonomy     {sum(len(v) for v in tax.values())} issues across {len(tax)} products")


def load(split: str) -> list[dict]:
    return [json.loads(line) for line in (DATA / f"{split}.jsonl").read_text().splitlines() if line.strip()]
