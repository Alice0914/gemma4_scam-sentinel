"""
Evaluate Scam Sentinel across multiple models on the hand-labeled eval set.

Usage:
    # Production: fine-tuned Gemma 4 E2B + QLoRA (the model on Ollama Hub)
    python scripts/evaluate.py --model gemma4-scam --output results/production.json

    # Legacy baselines (kept for the README "How we got here" section)
    python scripts/evaluate.py --model gemma3:4b --output results/eval300_gemma3.json
    python scripts/evaluate.py --model gemma3:4b --rag --output results/eval300_gemma3_rag.json
    python scripts/evaluate.py --model gemma4 --output results/eval300_gemma4_v3.json

    # Compare any set of result files
    python scripts/evaluate.py --compare results/production.json results/eval300_gemma3.json
"""

import json
import argparse
import sys
from pathlib import Path
from collections import defaultdict

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
SYSTEM_PROMPT_PATH = Path("backend/prompts/system_prompt.md")
EVAL_SET_PATH = Path("data/evaluation/eval_set.jsonl")

RISK_ORDER = {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
HIGH_RISK = {"high", "critical"}
SCAM_LABELS = {"low", "medium", "high", "critical"}
SAFE_LABELS = {"safe"}


def load_eval_set(path: Path) -> list[dict]:
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def call_model(model: str, prompt: str, timeout: int = 300) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["response"].strip()


def extract_risk_level(raw: str) -> str:
    import re
    match = re.search(r'"risk_level"\s*:\s*"(safe|low|medium|high|critical)"', raw, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    for level in ["critical", "high", "medium", "low", "safe"]:
        if level in raw.lower():
            return level
    return "low"


def build_rag_context(text: str, retriever) -> str:
    """Return a formatted SIMILAR PAST CASES block, or empty string if no retriever."""
    if retriever is None:
        return ""
    cases = retriever.retrieve(text)
    if not cases:
        return ""
    lines = ["\n\nSIMILAR PAST CASES (for reference, not training):"]
    for i, case in enumerate(cases, 1):
        lines.append(
            f"[Case {i}] {case.get('title', '')}, {case.get('year', '')}\n"
            f"  Summary: {case.get('summary', '')}\n"
            f"  Outcome: {case.get('outcome', '')}"
        )
    lines.append("If the current input matches a known pattern, mention it in user_message.")
    return "\n".join(lines)


def evaluate_sample(sample: dict, model: str, system_prompt: str, retriever=None) -> dict:
    rag_block = build_rag_context(sample["text"], retriever)
    prompt = (
        f"{system_prompt}\n\n---\n\nANALYZE THIS INPUT:\n\n"
        f"TEXT: {sample['text']}\nMETADATA: {{\"channel\": \"{sample['channel']}\"}}"
        f"{rag_block}"
    )
    try:
        raw = call_model(model, prompt)
        predicted = extract_risk_level(raw)
    except Exception as e:
        predicted = "error"
        raw = str(e)

    true_label = sample["label"]
    # Binary: scam vs safe
    true_scam = true_label in SCAM_LABELS
    pred_scam = predicted in SCAM_LABELS

    return {
        "id": sample["id"],
        "true_label": true_label,
        "predicted": predicted,
        "true_scam": true_scam,
        "pred_scam": pred_scam,
        "correct": true_label == predicted,
        "correct_binary": true_scam == pred_scam,
        "category": sample.get("category", "unknown"),
        "raw_output": raw[:300],
    }


def compute_metrics(results: list[dict]) -> dict:
    tp = sum(1 for r in results if r["true_scam"] and r["pred_scam"])
    fp = sum(1 for r in results if not r["true_scam"] and r["pred_scam"])
    tn = sum(1 for r in results if not r["true_scam"] and not r["pred_scam"])
    fn = sum(1 for r in results if r["true_scam"] and not r["pred_scam"])

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
    accuracy = sum(1 for r in results if r["correct_binary"]) / len(results)

    # Per-category breakdown
    by_cat: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})
    for r in results:
        cat = r["category"]
        by_cat[cat]["total"] += 1
        if r["correct_binary"]:
            by_cat[cat]["correct"] += 1

    return {
        "total": len(results),
        "accuracy": round(accuracy, 3),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "false_positive_rate": round(fpr, 3),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "per_category": {k: {"accuracy": round(v["correct"]/v["total"], 3), "total": v["total"]} for k, v in by_cat.items()},
    }


def run_evaluation(model: str, output_path: Path, use_rag: bool = False) -> None:
    print(f"\n{'='*50}")
    print(f"Model: {model}" + (" + RAG" if use_rag else ""))
    print(f"{'='*50}")

    retriever = None
    if use_rag:
        import sys
        sys.path.insert(0, ".")
        from backend.rag import ScamCaseRetriever
        print("Loading RAG retriever...")
        retriever = ScamCaseRetriever(top_k=3)
        print(f"  RAG index: {retriever.collection.count()} cases")

    system_prompt = load_system_prompt()
    samples = load_eval_set(EVAL_SET_PATH)
    print(f"Evaluating {len(samples)} samples...")

    results = []
    for i, sample in enumerate(samples, 1):
        print(f"  [{i:02d}/{len(samples)}] {sample['id']} (true: {sample['label']})", end=" ")
        result = evaluate_sample(sample, model, system_prompt, retriever)
        results.append(result)
        status = "OK" if result["correct_binary"] else "WRONG"
        print(f"-> predicted: {result['predicted']} [{status}]")

    metrics = compute_metrics(results)

    output = {
        "model": model + (" +RAG" if use_rag else ""),
        "metrics": metrics,
        "results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nResults:")
    print(f"  Accuracy:           {metrics['accuracy']:.1%}")
    print(f"  Precision:          {metrics['precision']:.1%}")
    print(f"  Recall:             {metrics['recall']:.1%}")
    print(f"  F1:                 {metrics['f1']:.1%}")
    print(f"  False Positive Rate:{metrics['false_positive_rate']:.1%}")
    print(f"\nSaved to {output_path}")


def compare_results(result_files: list[str]) -> None:
    print(f"\n{'='*70}")
    print("COMPARISON TABLE")
    print(f"{'='*70}")
    print(f"{'Model':<30} {'Accuracy':>10} {'Precision':>10} {'Recall':>10} {'F1':>8} {'FPR':>8}")
    print("-" * 70)

    for path in result_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        m = data["metrics"]
        model = data["model"]
        print(f"{model:<30} {m['accuracy']:>10.1%} {m['precision']:>10.1%} {m['recall']:>10.1%} {m['f1']:>8.1%} {m['false_positive_rate']:>8.1%}")

    print("-" * 70)
    print("FPR = False Positive Rate (lower is better for user trust)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Scam Sentinel models")
    parser.add_argument("--model", type=str, default="gemma4", help="Ollama model name")
    parser.add_argument("--output", type=Path, default=Path("results/eval.json"))
    parser.add_argument("--rag", action="store_true", help="Inject RAG context from ChromaDB")
    parser.add_argument("--compare", nargs="+", help="Compare multiple result JSON files")
    args = parser.parse_args()

    if args.compare:
        compare_results(args.compare)
    else:
        run_evaluation(args.model, args.output, use_rag=args.rag)


if __name__ == "__main__":
    main()
