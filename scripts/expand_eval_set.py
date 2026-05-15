"""
Expand evaluation set from 70 to 300 samples.

Sources:
  - 70 existing hand-labeled samples (kept as-is)
  - UCI SMS Spam Collection — only samples NOT used in training (seeds_real.jsonl excluded)
  - 150 ham (normal) + 80 spam additions, keyword-categorised

Output:
  - data/evaluation/eval_set.jsonl       (300 samples, replaces original)
  - data/evaluation/eval_set_70.jsonl    (backup of original 70)
"""

import csv
import json
import random
import re
import shutil
from collections import Counter
from pathlib import Path

random.seed(42)

EVAL_PATH = Path("data/evaluation/eval_set.jsonl")
BACKUP_PATH = Path("data/evaluation/eval_set_70.jsonl")
SEEDS_REAL_PATH = Path("data/seeds_real.jsonl")
UCI_PATH = Path("data/sms_spam_collection/spam.csv")

TARGET_HAM = 150
TARGET_SPAM = 80


def load_existing_eval() -> list[dict]:
    samples = []
    with open(EVAL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def load_training_texts() -> set[str]:
    """Texts already in training (must NOT appear in eval)."""
    texts = set()
    with open(SEEDS_REAL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                t = d.get("text") or d.get("content") or ""
                texts.add(t.strip())
    return texts


def load_uci() -> list[tuple[str, str]]:
    """Returns [(label, text), ...] from UCI SMS Spam Collection."""
    rows = []
    with open(UCI_PATH, encoding="latin-1") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) >= 2 and row[0] in ("ham", "spam"):
                rows.append((row[0], row[1].strip()))
    return rows


# ── Spam categorisation by keyword heuristics ────────────────────────────────

def categorise_spam(text: str) -> tuple[str, str]:
    """Return (category, label) for a spam message based on keyword heuristics."""
    t = text.lower()

    has_link = bool(re.search(r"https?://|www\.|\.com|\.co\.uk|\.net|wap\.", t))
    has_money = bool(re.search(r"\b(£|\$|cash|prize|won|win|claim|reward|bonus|guaranteed)\b", t))
    has_credential = bool(re.search(r"\b(pin|password|otp|verify|account|ssn|social security)\b", t))
    has_urgency = bool(re.search(r"\b(urgent|now|immediately|expire|today|24 hours|act fast)\b", t))
    has_delivery = bool(re.search(r"\b(parcel|package|delivery|courier|usps|royal mail|fedex|ups)\b", t))
    has_bank = bool(re.search(r"\b(bank|hsbc|chase|wells fargo|barclays|lloyds|natwest|account suspended)\b", t))
    has_call = bool(re.search(r"\b(call \d|call now|ring \d|tel:|\+\d{6})\b", t))

    # Determine category
    if has_delivery:
        category = "package_scam"
    elif has_bank or "account" in t and "suspended" in t:
        category = "bank_phishing"
    elif has_money and (has_link or has_call):
        category = "phishing_link"
    elif has_link:
        category = "phishing_link"
    elif has_money:
        category = "phishing_link"  # generic prize/money scam without link
    else:
        category = "phishing_link"  # default for spam

    # Determine severity label
    if has_credential:
        label = "critical"
    elif (has_money and has_link) or (has_bank and has_link):
        label = "high"
    elif has_link or has_money or has_delivery:
        label = "medium"
    elif has_urgency:
        label = "low"
    else:
        label = "medium"  # any unsolicited spam = at least medium

    return category, label


def is_too_short_or_noise(text: str) -> bool:
    if len(text.strip()) < 15:
        return True
    if len(text.split()) < 4:
        return True
    return False


def main():
    # Backup original
    if not BACKUP_PATH.exists():
        shutil.copy(EVAL_PATH, BACKUP_PATH)
        print(f"Backed up original 70 -> {BACKUP_PATH}")

    existing = load_existing_eval()
    existing_texts = {s["text"].strip() for s in existing}
    training_texts = load_training_texts()
    print(f"Existing eval:   {len(existing)} samples")
    print(f"Training texts:  {len(training_texts)} (excluded from sampling)")

    uci = load_uci()
    print(f"UCI total:       {len(uci)} rows")

    # Filter UCI: exclude anything in training or already in eval, exclude noise
    available_ham = []
    available_spam = []
    for label, text in uci:
        t = text.strip()
        if t in training_texts or t in existing_texts:
            continue
        if is_too_short_or_noise(t):
            continue
        if label == "ham":
            available_ham.append(t)
        else:
            available_spam.append(t)

    print(f"Available ham:   {len(available_ham)}")
    print(f"Available spam:  {len(available_spam)}")

    # Sample
    random.shuffle(available_ham)
    random.shuffle(available_spam)
    sampled_ham = available_ham[:TARGET_HAM]
    sampled_spam = available_spam[:TARGET_SPAM]
    print(f"\nSampled:  {len(sampled_ham)} ham + {len(sampled_spam)} spam = {len(sampled_ham) + len(sampled_spam)} new")

    # Build new entries
    new_samples = []
    next_id = max(int(re.search(r"\d+", s["id"]).group()) for s in existing) + 1

    for text in sampled_ham:
        new_samples.append({
            "id": f"eval_{next_id:03d}",
            "label": "safe",
            "category": "normal",
            "channel": "sms",
            "text": text,
            "notes": "UCI ham (real)",
        })
        next_id += 1

    for text in sampled_spam:
        category, label = categorise_spam(text)
        new_samples.append({
            "id": f"eval_{next_id:03d}",
            "label": label,
            "category": category,
            "channel": "sms",
            "text": text,
            "notes": "UCI spam (real, keyword-categorised)",
        })
        next_id += 1

    # Combine + write
    all_samples = existing + new_samples
    with open(EVAL_PATH, "w", encoding="utf-8") as f:
        for s in all_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"\n[OK] Wrote {len(all_samples)} samples -> {EVAL_PATH}")
    print(f"  Categories: {Counter(s['category'] for s in all_samples)}")
    print(f"  Labels:     {Counter(s['label'] for s in all_samples)}")
    print(f"  Channels:   {Counter(s['channel'] for s in all_samples)}")


if __name__ == "__main__":
    main()
