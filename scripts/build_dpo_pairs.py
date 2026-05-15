"""Convert user feedback (👍/👎) into DPO preference pairs.

DPO needs (prompt, chosen, rejected) triples, but a single 👎 click only gives
us one side. We synthesize the other side using the following rule:

  • user_verdict == "false_alarm" (model over-flagged a benign message)
      rejected = the over-flagged response the model produced
      chosen   = a clean SAFE response (no patterns, no tools, calm message)
      → teaches: "don't yell scam on normal messages"

  • user_verdict == "correct"  AND  predicted_risk in {medium, high, critical}
      chosen   = the correct flagged response
      rejected = a synthesized "missed it" SAFE response
      → teaches: "don't go silent on real scams"

  • user_verdict == "correct"  AND  predicted_risk in {safe, low}
      skipped — pairing safe-vs-safe gives no useful preference signal.

Output: `data/dpo_pairs.jsonl`, one preference triple per line, ready for
trl.DPOTrainer with the Gemma 4 chat template.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_FEEDBACK = Path("data/user_feedback.jsonl")
DEFAULT_OUTPUT = Path("data/dpo_pairs.jsonl")
DEFAULT_SYSTEM_PROMPT = Path("backend/prompts/system_prompt.md")

FLAGGED_LEVELS = {"medium", "high", "critical"}


def build_user_prompt(record: dict) -> str:
    """Reconstruct the analyze-style user prompt the model was trained on."""
    channel = record.get("channel", "sms")
    text = record.get("input_text", "")
    if channel == "voice":
        return f"ANALYZE THIS INPUT:\n\nTRANSCRIPT: {text}"
    return f"ANALYZE THIS INPUT:\n\nTEXT: {text}"


def synthesize_safe_response(record: dict) -> str:
    """The 'this is fine' response we want the model to converge on for false alarms."""
    return json.dumps(
        {
            "risk_level": "safe",
            "patterns": [],
            "user_message": (
                "This message appears to be normal. No warning signs detected."
            ),
            "tool_calls": [],
        },
        ensure_ascii=False,
    )


def reconstruct_flagged_response(record: dict) -> str:
    """Rebuild the assistant turn the model actually produced when over-flagging."""
    excerpt = record.get("user_message_excerpt") or (
        f"This message looks suspicious due to: "
        f"{', '.join(record.get('predicted_patterns', [])) or 'unclear cues'}."
    )
    return json.dumps(
        {
            "risk_level": record.get("predicted_risk", "medium"),
            "patterns": record.get("predicted_patterns", []),
            "user_message": excerpt,
            "tool_calls": record.get("tool_calls", []),
        },
        ensure_ascii=False,
    )


def record_to_pair(record: dict, system_prompt: str) -> dict | None:
    verdict = record.get("user_verdict")
    risk = record.get("predicted_risk", "safe")

    if verdict == "false_alarm":
        rejected = reconstruct_flagged_response(record)
        chosen = synthesize_safe_response(record)
    elif verdict == "correct" and risk in FLAGGED_LEVELS:
        chosen = reconstruct_flagged_response(record)
        rejected = synthesize_safe_response(record)
    else:
        return None

    user_prompt = build_user_prompt(record)
    # Conversational format that trl.DPOTrainer accepts directly with apply_chat_template.
    return {
        "prompt": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "chosen": [{"role": "assistant", "content": chosen}],
        "rejected": [{"role": "assistant", "content": rejected}],
        "_source_verdict": verdict,
        "_source_risk": risk,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, default=DEFAULT_FEEDBACK)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--system-prompt", type=Path, default=DEFAULT_SYSTEM_PROMPT)
    args = p.parse_args()

    if not args.input.exists():
        print(f"[build_dpo_pairs] no feedback file at {args.input} — nothing to do.")
        return 0

    system_prompt = args.system_prompt.read_text(encoding="utf-8") if args.system_prompt.exists() else ""

    n_in = n_out = n_skipped = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.input.open("r", encoding="utf-8") as src, args.output.open("w", encoding="utf-8") as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            n_in += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                n_skipped += 1
                continue
            pair = record_to_pair(record, system_prompt)
            if pair is None:
                n_skipped += 1
                continue
            dst.write(json.dumps(pair, ensure_ascii=False) + "\n")
            n_out += 1

    print(f"[build_dpo_pairs] read {n_in} feedback records → {n_out} preference pairs ({n_skipped} skipped)")
    print(f"[build_dpo_pairs] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
