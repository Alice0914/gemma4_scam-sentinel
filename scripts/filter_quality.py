"""
Filter and deduplicate synthetic scam data.

Steps:
1. Drop samples containing meta-words (scam, fake, phishing, etc.)
2. Drop unrealistic monetary amounts (> $500,000)
3. Deduplicate using cosine similarity threshold (> 0.9 = near-duplicate)
4. Split into train (80%) and dev (20%)

Usage:
    pip install sentence-transformers scikit-learn
    python scripts/filter_quality.py \
        --input data/synthetic/raw.jsonl \
        --train data/synthetic/train.jsonl \
        --dev data/synthetic/dev.jsonl
"""

import json
import re
import random
import argparse
from pathlib import Path

import numpy as np

META_WORDS = {
    "scam", "fake", "phishing", "fraud", "fraudulent",
    "synthetic", "malicious", "deceptive", "criminal",
    "attacker", "hacker", "cybercriminal",
}

AMOUNT_PATTERN = re.compile(r"\$[\d,]+")
MAX_REALISTIC_AMOUNT = 500_000


def load_jsonl(path: Path) -> list[dict]:
    samples = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def write_jsonl(samples: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def has_meta_words(text: str) -> bool:
    words = set(re.findall(r"\b\w+\b", text.lower()))
    return bool(words & META_WORDS)


def has_unrealistic_amount(text: str) -> bool:
    for match in AMOUNT_PATTERN.findall(text):
        amount = int(match.replace("$", "").replace(",", ""))
        if amount > MAX_REALISTIC_AMOUNT:
            return True
    return False


def filter_by_content(samples: list[dict]) -> tuple[list[dict], dict]:
    kept = []
    dropped_meta = 0
    dropped_amount = 0

    for s in samples:
        text = s["text"]
        if has_meta_words(text):
            dropped_meta += 1
            continue
        if has_unrealistic_amount(text):
            dropped_amount += 1
            continue
        kept.append(s)

    stats = {
        "original": len(samples),
        "dropped_meta_words": dropped_meta,
        "dropped_unrealistic_amount": dropped_amount,
        "after_content_filter": len(kept),
    }
    return kept, stats


def deduplicate(samples: list[dict], threshold: float = 0.9) -> tuple[list[dict], int]:
    try:
        from sentence_transformers import SentenceTransformer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        print("WARNING: sentence-transformers not installed. Skipping deduplication.")
        print("Run: pip install sentence-transformers scikit-learn")
        return samples, 0

    print("Loading embedding model for deduplication...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    texts = [s["text"] for s in samples]
    print(f"Embedding {len(texts)} samples...")
    embeddings = model.encode(texts, batch_size=64, show_progress_bar=True)

    kept_indices = []
    dropped = 0

    for i in range(len(embeddings)):
        if not kept_indices:
            kept_indices.append(i)
            continue
        kept_embeddings = embeddings[kept_indices]
        sims = cosine_similarity([embeddings[i]], kept_embeddings)[0]
        if sims.max() < threshold:
            kept_indices.append(i)
        else:
            dropped += 1

    kept = [samples[i] for i in kept_indices]
    return kept, dropped


def train_dev_split(
    samples: list[dict],
    dev_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    random.seed(seed)
    # Stratified split by category
    by_category: dict[str, list[dict]] = {}
    for s in samples:
        by_category.setdefault(s["category"], []).append(s)

    train, dev = [], []
    for category, items in by_category.items():
        random.shuffle(items)
        n_dev = max(1, int(len(items) * dev_ratio))
        dev.extend(items[:n_dev])
        train.extend(items[n_dev:])

    random.shuffle(train)
    random.shuffle(dev)
    return train, dev


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter and split synthetic scam data")
    parser.add_argument(
        "--input", type=Path, default=Path("data/synthetic/raw.jsonl")
    )
    parser.add_argument(
        "--train", type=Path, default=Path("data/synthetic/train.jsonl")
    )
    parser.add_argument(
        "--dev", type=Path, default=Path("data/synthetic/dev.jsonl")
    )
    parser.add_argument(
        "--sim-threshold",
        type=float,
        default=0.9,
        help="Cosine similarity threshold for near-duplicate removal",
    )
    parser.add_argument(
        "--dev-ratio", type=float, default=0.2, help="Fraction held out for dev set"
    )
    parser.add_argument(
        "--skip-dedup",
        action="store_true",
        help="Skip deduplication (faster, for testing)",
    )
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    samples = load_jsonl(args.input)
    print(f"Loaded {len(samples)} samples")

    print("\nStep 1: Content filtering...")
    samples, stats = filter_by_content(samples)
    print(f"  Dropped (meta-words): {stats['dropped_meta_words']}")
    print(f"  Dropped (unrealistic amounts): {stats['dropped_unrealistic_amount']}")
    print(f"  Remaining: {stats['after_content_filter']}")

    if not args.skip_dedup:
        print("\nStep 2: Deduplication...")
        samples, n_dropped = deduplicate(samples, threshold=args.sim_threshold)
        print(f"  Dropped near-duplicates: {n_dropped}")
        print(f"  Remaining: {len(samples)}")
    else:
        print("\nStep 2: Skipping deduplication (--skip-dedup)")

    print("\nStep 3: Train/dev split...")
    train, dev = train_dev_split(samples, dev_ratio=args.dev_ratio)

    write_jsonl(train, args.train)
    write_jsonl(dev, args.dev)

    print(f"\nFinal dataset:")
    print(f"  Train: {len(train)} samples ->{args.train}")
    print(f"  Dev:   {len(dev)} samples ->{args.dev}")

    # Per-category breakdown
    print("\nCategory breakdown (train):")
    by_cat: dict[str, int] = {}
    for s in train:
        by_cat[s["category"]] = by_cat.get(s["category"], 0) + 1
    for cat, count in sorted(by_cat.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
