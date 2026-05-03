"""
Fetch LIAR dataset, remap to project's 8-topic taxonomy and 5-verdict scale,
and produce two CSVs matching the existing synthetic_train_*.csv schema:

  liar_train.csv  — bulk corpus for routing classifier training
  liar_eval.csv   — 200-row stratified sample for Level 7 eval

Usage:
  python fetch_liar.py
  python fetch_liar.py --eval-size 300 --out-dir .

The LIAR dataset (Wang 2017) is ~12.8K PolitiFact claims with 6-way verdicts and
free-form subject tags. We map subjects to {immigration, healthcare, crime,
economy, education, legal_political, elections, foreign_policy} and drop rows
that don't fit any of the 8. Verdicts collapse to {True, Mostly True, Mixed,
Mostly False, False}.

Topic mapping is a hand-curated allowlist of PolitiFact subject substrings.
Anything not matched is excluded — we'd rather have 5K clean labels than 12K
noisy ones. Multi-label is the norm: e.g. ``criminal-justice`` claims map to
both ``crime`` and ``legal_political``; ``terrorism`` claims that mention Iraq
map to both ``foreign_policy``.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

LIAR_URL = "https://www.cs.ucsb.edu/~william/data/liar_dataset.zip"

# LIAR TSV columns (no header in the file)
LIAR_COLUMNS = [
    "id", "label", "statement", "subject", "speaker", "job_title",
    "state_info", "party_affiliation",
    "barely_true_counts", "false_counts", "half_true_counts",
    "mostly_true_counts", "pants_on_fire_counts",
    "context",
]

# PolitiFact 6-way verdict → project's 5-way verdict
VERDICT_MAP = {
    "true":         "True",
    "mostly-true":  "Mostly True",
    "half-true":    "Mixed",
    "barely-true":  "Mostly False",
    "false":        "False",
    "pants-fire":   "False",
}

# Subject keyword → project topic. PolitiFact's `subject` column is comma-separated
# fine-grained tags like "immigration,border-security". We check substring containment.
TOPIC_RULES: dict[str, list[str]] = {
    "immigration": [
        "immigration", "border", "border-security", "deportation", "asylum",
        "refugee", "visas", "citizenship", "ice", "uscis", "dreamer", "daca",
    ],
    "healthcare": [
        "health", "health-care", "healthcare", "medicare", "medicaid",
        "medicaid-expansion", "obamacare", "affordable-care-act", "abortion",
        "abortion-rights", "drugs", "prescription-drugs", "mental-health",
        "public-health", "fda", "cdc", "vaccines", "covid", "coronavirus",
    ],
    "crime": [
        "crime", "criminal-justice", "guns", "gun-control", "death-penalty",
        "drugs", "drug-policy", "policing", "police", "prison", "corrections",
        "marijuana", "homicide", "violent-crime",
    ],
    "economy": [
        "economy", "economic", "jobs", "job-growth", "unemployment", "wages",
        "inflation", "taxes", "tax-policy", "deficit", "debt", "budget",
        "trade", "tariffs", "manufacturing", "small-business", "stocks",
        "stock-market", "wall-street", "federal-reserve", "income", "poverty",
        "minimum-wage", "social-security", "medicare-spending",
    ],
    "education": [
        "education", "schools", "k-12", "higher-education", "college",
        "universities", "student-loans", "student-debt", "teachers",
        "school-choice", "charter-schools", "vouchers", "title-ix",
        "head-start", "pell-grants",
    ],
    # Specific legal proceedings against public figures — distinct from
    # ``crime`` (which is aggregate offense statistics). We deliberately
    # do NOT include ``criminal-justice`` here even though it overlaps:
    # double-labeling that tag bled probability mass between the two
    # classes and dropped legal_political F1 to 0.51. Keeping
    # criminal-justice as pure-``crime`` makes legal_political's positives
    # cleaner (specific lawsuits / rulings / impeachments / ethics cases).
    "legal_political": [
        "legal-issues", "supreme-court", "impeachment", "ethics",
    ],
    # Election administration and campaigns. Deliberately excludes
    # ``voting-record`` — that's a politician's *legislative* voting
    # history, not election administration; it does not belong with the
    # FEC/EAC allowlist of ElectionsAgent.
    "elections": [
        "elections", "campaign-finance", "campaign-advertising", "polls",
        "redistricting",
    ],
    "foreign_policy": [
        "foreign-policy", "military", "terrorism", "iraq", "afghanistan",
        "china", "israel", "iran", "russia", "ukraine", "north-korea",
        "syria",
    ],
}

CANONICAL_TOPICS = (
    "immigration", "healthcare", "crime", "economy", "education",
    "legal_political", "elections", "foreign_policy",
)


def download_liar() -> dict[str, list[list[str]]]:
    """Fetch the LIAR zip and return parsed train/valid/test splits."""
    print(f"Fetching {LIAR_URL} ...", file=sys.stderr)
    with urllib.request.urlopen(LIAR_URL) as resp:
        zip_bytes = resp.read()

    splits: dict[str, list[list[str]]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if not name.endswith(".tsv"):
                continue
            split = Path(name).stem  # train / valid / test
            with zf.open(name) as fh:
                rows = list(csv.reader(io.TextIOWrapper(fh, encoding="utf-8"),
                                       delimiter="\t"))
            splits[split] = rows
            print(f"  {split}: {len(rows)} rows", file=sys.stderr)
    return splits


def map_subjects_to_topics(subject_field: str) -> list[str]:
    """PolitiFact subjects → 0..N of our canonical topic ids."""
    if not subject_field:
        return []
    fragments = [s.strip().lower() for s in subject_field.split(",") if s.strip()]
    matched: set[str] = set()
    for topic, keywords in TOPIC_RULES.items():
        for fragment in fragments:
            if any(kw == fragment or kw in fragment for kw in keywords):
                matched.add(topic)
                break
    return sorted(matched)


def remap_row(row: list[str]) -> dict | None:
    """Convert one LIAR TSV row to our schema. Returns None if unusable."""
    if len(row) < len(LIAR_COLUMNS):
        return None
    record = dict(zip(LIAR_COLUMNS, row))
    statement = record["statement"].strip()
    label = record["label"].strip()

    if not statement or label not in VERDICT_MAP:
        return None

    topics = map_subjects_to_topics(record["subject"])
    if not topics:
        return None  # drop rows that don't fit any of our 5 topics

    return {
        "claim_text": statement,
        "verdict": VERDICT_MAP[label],
        "topics": topics,
        "speaker": record["speaker"].strip(),
    }


def to_csv_rows(records: list[dict]) -> list[list]:
    """Project schema: claim_text, immigration, healthcare, crime, economy, education, verdict, speaker."""
    rows = []
    for r in records:
        labels = [1 if t in r["topics"] else 0 for t in CANONICAL_TOPICS]
        rows.append([r["claim_text"], *labels, r["verdict"], r["speaker"]])
    return rows


def stratified_eval_sample(records: list[dict], target_size: int) -> tuple[list[dict], list[dict]]:
    """Pull a stratified sample for eval. Remaining records become training set.

    Aims for ~equal coverage across the 5 topics. Some claims are multi-label
    so totals may exceed target_size slightly.
    """
    per_topic = max(1, target_size // len(CANONICAL_TOPICS))
    eval_records: list[dict] = []
    eval_ids: set[int] = set()

    by_topic: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for idx, r in enumerate(records):
        for t in r["topics"]:
            by_topic[t].append((idx, r))

    # Round-robin pick per topic, prefer single-label claims first to keep eval crisp
    for topic in CANONICAL_TOPICS:
        bucket = by_topic.get(topic, [])
        # Prefer single-label first; multi-label muddies per-topic accuracy
        bucket.sort(key=lambda pair: (len(pair[1]["topics"]), pair[0]))
        picked = 0
        for idx, r in bucket:
            if idx in eval_ids:
                continue
            eval_records.append(r)
            eval_ids.add(idx)
            picked += 1
            if picked >= per_topic:
                break

    train_records = [r for i, r in enumerate(records) if i not in eval_ids]
    return train_records, eval_records


def write_csv(path: Path, rows: list[list], header: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(header)
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows → {path}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-size", type=int, default=200,
                        help="Approximate eval row count (stratified across 5 topics).")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent,
                        help="Where to write liar_train.csv and liar_eval.csv.")
    args = parser.parse_args()

    splits = download_liar()
    all_rows = splits.get("train", []) + splits.get("valid", []) + splits.get("test", [])
    print(f"Total LIAR rows: {len(all_rows)}", file=sys.stderr)

    records: list[dict] = []
    drops = Counter()
    for row in all_rows:
        rec = remap_row(row)
        if rec is None:
            drops["unmapped_or_invalid"] += 1
            continue
        records.append(rec)

    print(f"Kept after topic+verdict mapping: {len(records)}", file=sys.stderr)
    print(f"Dropped (no matching topic, bad verdict, or malformed): "
          f"{drops['unmapped_or_invalid']}", file=sys.stderr)

    # Per-topic counts (multi-label so totals can exceed len(records))
    topic_counts = Counter()
    for r in records:
        for t in r["topics"]:
            topic_counts[t] += 1
    print("Per-topic coverage:", file=sys.stderr)
    for t in CANONICAL_TOPICS:
        print(f"  {t:>15}: {topic_counts[t]}", file=sys.stderr)

    train_records, eval_records = stratified_eval_sample(records, args.eval_size)
    print(f"Split: {len(train_records)} train / {len(eval_records)} eval",
          file=sys.stderr)

    header = ["claim_text", *CANONICAL_TOPICS, "verdict", "speaker"]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "liar_train.csv",
              to_csv_rows(train_records), header)
    write_csv(args.out_dir / "liar_eval.csv",
              to_csv_rows(eval_records), header)
    return 0


if __name__ == "__main__":
    sys.exit(main())
