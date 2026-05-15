"""
Extract and classify real spam messages from UCI SMS Spam Collection.
Outputs classified spam as seeds for synthetic data generation.

Usage:
    python scripts/extract_real_seeds.py \
        --output data/seeds_real.jsonl
"""

import csv
import json
import re
import argparse
from pathlib import Path

SPAM_CSV = Path("data/sms_spam_collection/spam.csv")

# Keyword-based category classifier
CATEGORY_RULES = [
    ("bank_phishing", [
        r"bank", r"account\s*(suspended|locked|limited|verify)",
        r"(paypal|chase|wellsfargo|citibank|hsbc|barclays)",
        r"login.*verif", r"password.*expir", r"credit.card",
        r"billing.*update", r"payment.*fail",
    ]),
    ("phishing_link", [
        r"(won|winner|selected|congratul)", r"prize", r"reward",
        r"gift.card", r"claim.*now", r"free.*iphone",
        r"click.*link", r"survey.*complete",
        r"http[s]?://\S+", r"www\.\S+",
    ]),
    ("package_scam", [
        r"(usps|fedex|dhl|ups|royal.mail|parcel|package|delivery)",
        r"customs.*fee", r"redelivery", r"shipment.*hold",
    ]),
    ("prosecutor_scam", [
        r"(irs|fbi|police|sheriff|court|warrant|arrest)",
        r"social.security", r"tax.*owe", r"law.enforcement",
        r"fine.*pay", r"legal.action",
    ]),
    ("romance_scam", [
        r"darling|sweetheart|my love|dearest|honey",
        r"military.*deployed", r"meet.*soon", r"lonely",
        r"feel.*connection",
    ]),
    ("family_impersonation", [
        r"(mom|dad|grandma|grandpa|son|daughter|grandson|granddaughter)",
        r"it'?s me.*help", r"stranded|arrested|accident|hospital",
        r"bail|lawyer.*need",
    ]),
]

PATTERN_RULES = {
    "urgency": [
        r"(right now|immediately|urgent|asap|hurry|limited time|expires?|within \d+ hours?|today only|act now)",
    ],
    "impersonation": [
        r"(this is|i am|it'?s me).{0,30}(officer|agent|bank|irs|fbi|police|your (son|daughter|grandson))",
    ],
    "phishing_link": [
        r"(http[s]?://|www\.)\S+",
        r"\b[\w-]+\.(com|net|org|xyz|info)/\S*",
    ],
    "credential_request": [
        r"(password|pin|ssn|social security|otp|verify.*identity|confirm.*details)",
    ],
    "secrecy": [
        r"(don'?t tell|keep.*secret|between us|confidential|don'?t let.*know)",
    ],
    "new_account": [
        r"(new account|different account|bank account|routing|wire.*transfer|gift card)",
    ],
    "phone_avoidance": [
        r"(don'?t call|can'?t talk|phone.*broken|text only|no calls)",
    ],
}

NON_ENGLISH_PATTERN = re.compile(r"[^\x00-\x7F]{3,}")
MIN_LENGTH = 30
MAX_LENGTH = 500

META_WORDS = re.compile(
    r"\b(scam|phishing|fraudulent|malicious|fake message)\b", re.IGNORECASE
)


def classify_category(text: str) -> str:
    text_lower = text.lower()
    for category, patterns in CATEGORY_RULES:
        for pat in patterns:
            if re.search(pat, text_lower):
                return category
    return "phishing_link"  # default for unmatched spam


def detect_patterns(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    for pattern_name, regexes in PATTERN_RULES.items():
        for pat in regexes:
            if re.search(pat, text_lower, re.IGNORECASE):
                found.append(pattern_name)
                break
    return found if found else ["urgency"]


def is_usable(text: str) -> bool:
    if len(text) < MIN_LENGTH or len(text) > MAX_LENGTH:
        return False
    if NON_ENGLISH_PATTERN.search(text):
        return False
    if META_WORDS.search(text):
        return False
    return True


def load_spam(path: Path) -> list[str]:
    messages = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) >= 2 and row[0].strip().lower() == "spam":
                text = row[1].strip()
                if is_usable(text):
                    messages.append(text)
    return messages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/seeds_real.jsonl"))
    args = parser.parse_args()

    print(f"Loading spam from {SPAM_CSV}...")
    messages = load_spam(SPAM_CSV)
    print(f"Usable spam messages: {len(messages)}")

    # Deduplicate
    seen = set()
    unique = []
    for m in messages:
        key = m[:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append(m)
    print(f"After dedup: {len(unique)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(args.output, "w", encoding="utf-8") as f:
        for i, text in enumerate(unique):
            category = classify_category(text)
            patterns = detect_patterns(text)
            seed = {
                "id": f"real_{i+1:03d}",
                "category": category,
                "channel": "sms",
                "text": text,
                "patterns": patterns,
                "source": "real_uci",
            }
            f.write(json.dumps(seed, ensure_ascii=False) + "\n")
            written += 1

    print(f"Wrote {written} real seeds to {args.output}")

    # Category breakdown
    from collections import Counter
    cats: list[str] = []
    with open(args.output, encoding="utf-8") as f:
        for line in f:
            cats.append(json.loads(line)["category"])
    print("\nCategory breakdown:")
    for cat, count in Counter(cats).most_common():
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
