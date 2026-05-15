"""
Generate synthetic scam training data using Gemma 4 via Ollama.

Usage:
    python scripts/generate_synthetic.py --n-variants 50 --output data/synthetic/raw.jsonl
    python scripts/generate_synthetic.py --n-variants 5 --dry-run   # quick test
"""

import json
import time
import argparse
import requests
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "gemma4"
DEFAULT_SEEDS_PATH = Path("data/seeds.jsonl")
SYNTHESIS_PROMPT_PATH = Path("backend/prompts/synthesis.md")


def load_seeds(path: Path) -> list[dict]:
    seeds = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                seeds.append(json.loads(line))
    return seeds


def load_synthesis_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_prompt(template: str, seed: dict, n_variants: int) -> str:
    return template.format(
        category=seed["category"],
        channel=seed["channel"],
        patterns=", ".join(seed["patterns"]) if seed["patterns"] else "none",
        seed_text=seed["text"],
        n_variants=n_variants,
    )


def call_ollama(prompt: str, temperature: float = 0.8, max_retries: int = 3) -> str:
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": 2048,
            "top_p": 0.9,
        },
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
            resp.raise_for_status()
            return resp.json()["response"].strip()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            print(f"  Retry {attempt + 1}/{max_retries} after error: {e}")
            time.sleep(2 ** attempt)
    return ""


def parse_variants(raw_output: str, seed: dict) -> list[dict]:
    lines = [line.strip() for line in raw_output.strip().splitlines()]
    variants = []
    for i, line in enumerate(lines):
        if not line:
            continue
        # Skip lines that look like headers or numbering artifacts
        if line.startswith("#") or (len(line) < 15 and line.endswith(":")):
            continue
        variants.append({
            "id": f"{seed['id']}_v{i+1:03d}",
            "category": seed["category"],
            "channel": seed["channel"],
            "patterns": seed["patterns"],
            "text": line,
            "source": "synthetic",
            "seed_id": seed["id"],
        })
    return variants


def generate_for_seed(
    seed: dict,
    template: str,
    n_variants: int,
    dry_run: bool = False,
) -> list[dict]:
    prompt = build_prompt(template, seed, n_variants)

    if dry_run:
        print(f"  [DRY RUN] Would call Ollama for seed: {seed['id']}")
        return []

    print(f"  Generating {n_variants} variants for {seed['id']}...")
    raw = call_ollama(prompt)
    variants = parse_variants(raw, seed)
    print(f"  Got {len(variants)} variants")
    return variants


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic scam data via Ollama")
    parser.add_argument("--n-variants", type=int, default=50, help="Variants per seed")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/synthetic/raw.jsonl"),
        help="Output JSONL path",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Only generate for this category (optional)",
    )
    parser.add_argument(
        "--seeds",
        type=Path,
        default=DEFAULT_SEEDS_PATH,
        help="Path to seeds JSONL file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompts without calling Ollama",
    )
    args = parser.parse_args()

    seeds = load_seeds(args.seeds)
    template = load_synthesis_prompt(SYNTHESIS_PROMPT_PATH)

    if args.category:
        seeds = [s for s in seeds if s["category"] == args.category]
        print(f"Filtered to {len(seeds)} seeds for category: {args.category}")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    total_written = 0
    with open(args.output, "a", encoding="utf-8") as out_f:
        for i, seed in enumerate(seeds, 1):
            print(f"[{i}/{len(seeds)}] {seed['category']} — {seed['id']}")
            variants = generate_for_seed(seed, template, args.n_variants, args.dry_run)
            for v in variants:
                out_f.write(json.dumps(v, ensure_ascii=False) + "\n")
            total_written += len(variants)
            # Small delay to avoid overwhelming Ollama
            if not args.dry_run:
                time.sleep(0.5)

    print(f"\nDone. Wrote {total_written} samples to {args.output}")


if __name__ == "__main__":
    main()
