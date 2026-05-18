"""
Self-Improving Cascade — Loop A (Constitutional Self-Critique).

Reads recent user 👎 (false_alarm) feedback, asks Gemma 4 to propose a minimal
revision of the deep-reasoner system prompt, A/B evaluates the candidate against
the current prompt on a stratified subset of the real evaluation set, and
promotes the winner only if F1 does not drop AND false-positive rate goes down.

Typical use:
    # Inspect what would happen (no file changes)
    python scripts/self_critique.py --dry-run

    # Actually promote a winning candidate
    python scripts/self_critique.py --apply

Design notes:
- Targets `backend/prompts/system_prompt.md` (the single-model fine-tuned
  Gemma 4 reasoner used in production) since that is where the eval shows
  the biggest calibration headroom.
- Only false-alarm entries where the predicted risk was NOT "safe" are
  analyzed — a "safe" prediction means the model produced no warning, so
  there is nothing to revise.
- Eval defaults to 50 stratified samples for speed (~5 min). Use --full for
  the whole 300-sample set when running on a schedule.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

# Make `backend.*` importable when this script is invoked from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.evaluate import (  # noqa: E402
    compute_metrics,
    evaluate_sample,
    load_eval_set,
)

OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"

FEEDBACK_PATH       = Path("data/user_feedback.jsonl")
EVAL_SET_PATH       = Path("data/evaluation/eval_set.jsonl")
SYSTEM_PROMPT_PATH  = Path("backend/prompts/system_prompt.md")
CANDIDATE_PROMPT    = Path("backend/prompts/system_prompt_candidate.md")
PROMPT_HISTORY_DIR  = Path("backend/prompts/history")
PROMPT_VERSIONS_LOG = Path("docs/prompt_versions.md")
CRITIQUE_LOG_DIR    = Path("docs/self_critique_runs")

DEEP_MODEL = "gemma4"


# ── Step 1: load false-alarm feedback ────────────────────────────────────────

def load_false_alarms(path: Path, limit: int) -> list[dict]:
    """Most recent `limit` false-alarm entries with a non-safe predicted risk."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("user_verdict") != "false_alarm":
                continue
            if row.get("predicted_risk", "safe") == "safe":
                # Belongs to fast-classifier critique loop; skip here.
                continue
            rows.append(row)
    return rows[-limit:]


# ── Step 2: ask Gemma 4 to propose a revised prompt ──────────────────────────

CRITIQUE_INSTRUCTION = """\
You are reviewing the system prompt of a scam-detection assistant.

Real users flagged the following predictions as FALSE ALARMS — the assistant
classified each message as risky when it was actually benign. Each entry shows
the input the user pasted, the risk level the model assigned, the patterns it
claimed to detect, and a short excerpt of the user-facing explanation.

YOUR TASK:
1. Identify the recurring failure pattern across these false alarms.
2. Propose a MINIMAL, surgical revision to the system prompt below (ideally 1-3
   added or modified lines) that would prevent the same false alarms WITHOUT
   weakening detection of real scams.
3. Output the FULL revised prompt, ready to save back to disk. No diff markers,
   no commentary, no markdown fences. Just the raw revised prompt text.

CONSTRAINTS:
- Do not delete the "CONTROL CLASS - NORMAL" examples; they are load-bearing.
- Do not change the JSON output schema (risk_level / patterns / user_message /
  tool_calls fields must stay).
- Do not remove any of the 7 scam patterns.
- Keep the CoT 5-step structure intact.
- Preserve all SAFE-by-default rules; only ADD clarifications, do not relax.

If the false alarms are too varied to address with a single revision, output the
sentinel string `NO_REVISION` (uppercase, no other text) and nothing else.
"""


def build_critique_prompt(current_prompt: str, false_alarms: list[dict]) -> str:
    feedback_block_lines = []
    for i, fa in enumerate(false_alarms, 1):
        feedback_block_lines.append(
            f"[False alarm {i}] channel={fa.get('channel', '?')}, "
            f"predicted_risk={fa.get('predicted_risk', '?')}, "
            f"patterns={fa.get('predicted_patterns', [])}\n"
            f"  INPUT: {fa.get('input_text', '')[:500]}\n"
            f"  MODEL_EXPLANATION_EXCERPT: {fa.get('user_message_excerpt', '')[:300]}"
        )
    feedback_block = "\n\n".join(feedback_block_lines) or "(no false alarms recorded)"

    return (
        f"{CRITIQUE_INSTRUCTION}\n\n"
        f"=== CURRENT SYSTEM PROMPT (verbatim) ===\n{current_prompt}\n\n"
        f"=== FALSE ALARMS TO ADDRESS ===\n{feedback_block}\n\n"
        f"=== OUTPUT (full revised prompt text, or `NO_REVISION`) ==="
    )


def propose_revision(current_prompt: str, false_alarms: list[dict]) -> str | None:
    """Returns revised prompt text, or None if the model declined."""
    prompt = build_critique_prompt(current_prompt, false_alarms)
    resp = requests.post(
        OLLAMA_GENERATE_URL,
        json={
            "model": DEEP_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 4096, "num_ctx": 8192},
        },
        timeout=900,
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    if not raw:
        return None
    if raw.startswith("NO_REVISION"):
        return None
    # Strip any accidental markdown fence the model added.
    raw = re.sub(r"^```[a-zA-Z]*\n", "", raw)
    raw = re.sub(r"\n```\s*$", "", raw)
    return raw.strip()


# ── Step 3: A/B evaluate current vs candidate on stratified subset ───────────

def stratified_sample(samples: list[dict], n: int, seed: int = 0) -> list[dict]:
    """Sample n items keeping per-label proportions (best-effort)."""
    if n >= len(samples):
        return samples
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        buckets[s.get("label", "unknown")].append(s)
    out: list[dict] = []
    for label, group in buckets.items():
        rng.shuffle(group)
        take = max(1, round(n * len(group) / len(samples)))
        out.extend(group[:take])
    rng.shuffle(out)
    return out[:n]


def evaluate_prompt(prompt_text: str, samples: list[dict], model: str) -> dict:
    """Run the eval pipeline against an arbitrary system prompt string."""
    results = []
    total = len(samples)
    for i, sample in enumerate(samples, 1):
        result = evaluate_sample(sample, model=model, system_prompt=prompt_text, retriever=None)
        results.append(result)
        if i % 10 == 0 or i == total:
            correct = sum(1 for r in results if r["correct_binary"])
            print(f"  [{i:3d}/{total}] running accuracy: {correct / i:.1%}", flush=True)
    return compute_metrics(results)


# ── Step 4: promote or discard ───────────────────────────────────────────────

def candidate_is_better(curr: dict, cand: dict) -> tuple[bool, str]:
    """Win condition: F1 does not drop AND false-positive rate strictly decreases."""
    f1_ok  = cand["f1"] >= curr["f1"] - 1e-6
    fpr_ok = cand["false_positive_rate"] < curr["false_positive_rate"] - 1e-6
    if f1_ok and fpr_ok:
        return True, "F1 held and FPR decreased"
    if not f1_ok:
        return False, f"F1 dropped ({curr['f1']:.3f} -> {cand['f1']:.3f})"
    return False, (
        f"FPR did not decrease ({curr['false_positive_rate']:.3f} -> "
        f"{cand['false_positive_rate']:.3f})"
    )


def promote_candidate(candidate_text: str, curr_metrics: dict, cand_metrics: dict, n_fa: int) -> str:
    """Atomically swap system_prompt.md, archive the previous version, append to log."""
    PROMPT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = PROMPT_HISTORY_DIR / f"system_prompt_{ts}.md"
    shutil.copy2(SYSTEM_PROMPT_PATH, archive_path)
    SYSTEM_PROMPT_PATH.write_text(candidate_text, encoding="utf-8")

    log_entry = (
        f"\n## Auto-promoted by self_critique.py at {ts}\n\n"
        f"- False alarms reviewed: {n_fa}\n"
        f"- Previous F1: {curr_metrics['f1']:.3f} → New F1: {cand_metrics['f1']:.3f}\n"
        f"- Previous FPR: {curr_metrics['false_positive_rate']:.3f} → "
        f"New FPR: {cand_metrics['false_positive_rate']:.3f}\n"
        f"- Archived previous prompt: `{archive_path.as_posix()}`\n"
    )
    PROMPT_VERSIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PROMPT_VERSIONS_LOG.open("a", encoding="utf-8") as f:
        f.write(log_entry)
    return archive_path.as_posix()


def write_run_log(payload: dict) -> Path:
    CRITIQUE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = CRITIQUE_LOG_DIR / f"run_{ts}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


# ── Orchestration ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Loop A — Constitutional Self-Critique")
    parser.add_argument("--n-feedback", type=int, default=10,
                        help="Most recent false alarms to feed the critique (default 10)")
    parser.add_argument("--n-eval", type=int, default=50,
                        help="Stratified eval subset size (default 50; use 0 with --full for all)")
    parser.add_argument("--full", action="store_true",
                        help="Evaluate on the full eval set instead of a sample (slow)")
    parser.add_argument("--model", default="gemma4",
                        help="Model used for A/B evaluation (default gemma4)")
    parser.add_argument("--apply", action="store_true",
                        help="Actually promote the candidate if it wins (default dry-run)")
    args = parser.parse_args()

    print(f"[loop A] dry_run={not args.apply}, model={args.model}, "
          f"n_feedback={args.n_feedback}, n_eval={'all' if args.full else args.n_eval}")

    # 1. Pull false alarms
    false_alarms = load_false_alarms(FEEDBACK_PATH, limit=args.n_feedback)
    print(f"[loop A] loaded {len(false_alarms)} false-alarm feedback entries")
    if not false_alarms:
        print("[loop A] nothing to critique — exiting clean.")
        return

    # 2. Propose revision
    current_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    print(f"[loop A] asking {DEEP_MODEL} for a revised prompt...")
    candidate = propose_revision(current_prompt, false_alarms)
    if candidate is None:
        print("[loop A] model declined to propose a revision (NO_REVISION). Done.")
        return

    CANDIDATE_PROMPT.write_text(candidate, encoding="utf-8")
    print(f"[loop A] candidate prompt written to {CANDIDATE_PROMPT}")

    # 3. A/B evaluate
    all_samples = load_eval_set(EVAL_SET_PATH)
    eval_samples = all_samples if args.full else stratified_sample(all_samples, args.n_eval)
    print(f"[loop A] evaluating CURRENT prompt on {len(eval_samples)} samples...")
    curr_metrics = evaluate_prompt(current_prompt, eval_samples, args.model)
    print(f"[loop A]   current  F1={curr_metrics['f1']:.3f}  "
          f"FPR={curr_metrics['false_positive_rate']:.3f}")

    print(f"[loop A] evaluating CANDIDATE prompt on the same samples...")
    cand_metrics = evaluate_prompt(candidate, eval_samples, args.model)
    print(f"[loop A]   candidate F1={cand_metrics['f1']:.3f}  "
          f"FPR={cand_metrics['false_positive_rate']:.3f}")

    better, reason = candidate_is_better(curr_metrics, cand_metrics)
    print(f"[loop A] verdict: {'PROMOTE' if better else 'KEEP CURRENT'} — {reason}")

    # 4. Promote (or not)
    archive = None
    if better and args.apply:
        archive = promote_candidate(candidate, curr_metrics, cand_metrics, len(false_alarms))
        print(f"[loop A] previous prompt archived at {archive}")
        print(f"[loop A] system_prompt.md updated. Append entry in {PROMPT_VERSIONS_LOG}.")
    elif better:
        print("[loop A] candidate wins but --apply not set; no files were modified.")

    # 5. Persist a run log either way
    run_log = write_run_log({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": not args.apply,
        "n_false_alarms": len(false_alarms),
        "eval_subset_size": len(eval_samples),
        "model": args.model,
        "current_metrics": curr_metrics,
        "candidate_metrics": cand_metrics,
        "promoted": bool(better and args.apply),
        "decision_reason": reason,
        "archived_previous": archive,
    })
    print(f"[loop A] run log saved to {run_log}")


if __name__ == "__main__":
    main()
