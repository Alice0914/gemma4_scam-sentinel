"""Repair systematic label errors in data/synthetic/train_chat.jsonl.

Two error classes the audit surfaced:

  1. The text contains a shortlink / suspicious-domain marker (bit.ly,
     tinyurl, t.co, goo.gl, short.link, .xyz, .click) but the assistant
     output does NOT include the `phishing_link` pattern. We add it,
     and add `check_url_safety` to the tool_calls if missing.

  2. The assistant output classifies the message as `critical` but only
     lists a single pattern. The system prompt rule states `critical`
     requires 3+ patterns AND a money/credential request — a single
     pattern can never legitimately reach `critical`. We downgrade
     these to `medium` (still flagged, but no longer a rule violation).

Both the final JSON block AND the visible "Step 2 - ASSESS" line in the
chain-of-thought prose are updated, so the model is not trained on
self-contradicting samples.

Run:
    python scripts/fix_train_labels.py
    # Writes data/synthetic/train_chat.fixed.jsonl by default.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SHORTLINK_MARKERS = ("bit.ly", "tinyurl", "t.co/", "goo.gl", "short.link", ".xyz", ".click")

ASSESS_LINE_RE = re.compile(
    r"(Step 2 - ASSESS: )(\d+) pattern\(s\) detected, risk level: (\w+)\.",
)
# Synthetic data wraps the verdict in a ```json ... ``` markdown fence.
JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n```\s*$", re.DOTALL)


def fix_record(rec: dict) -> tuple[dict, list[str]]:
    """Returns (fixed_record, list_of_fixes_applied)."""
    fixes: list[str] = []
    msgs = rec["messages"]
    user_content = msgs[1]["content"]
    asst_content = msgs[2]["content"]

    # Find the final ```json fenced block in the assistant message.
    json_match = JSON_FENCE_RE.search(asst_content)
    if not json_match:
        return rec, fixes
    json_text = json_match.group(1)
    try:
        obj = json.loads(json_text)
    except json.JSONDecodeError:
        return rec, fixes

    risk = obj.get("risk_level", "")
    patterns = obj.get("patterns", []) or []
    tool_calls = obj.get("tool_calls", []) or []

    # --- Fix 1: shortlink → phishing_link ---
    user_low = user_content.lower()
    has_shortlink = any(m in user_low for m in SHORTLINK_MARKERS)
    if has_shortlink and "phishing_link" not in patterns:
        patterns.append("phishing_link")
        fixes.append("added_phishing_link")
        # Also wire up check_url_safety tool if no URL-safety tool yet.
        if not any(t.get("name") == "check_url_safety" for t in tool_calls):
            tool_calls.append({
                "name": "check_url_safety",
                "parameters": {"url": "(extracted from message)", "detected_in": "sms"},
            })
            fixes.append("added_check_url_safety_tool")

    # --- Fix 2: critical with single pattern → medium ---
    if risk == "critical" and len(patterns) <= 1:
        risk = "medium"
        fixes.append("downgraded_critical_to_medium")

    if not fixes:
        return rec, fixes

    obj["risk_level"] = risk
    obj["patterns"] = patterns
    obj["tool_calls"] = tool_calls

    # Re-emit the fenced JSON in place; preserve the surrounding markdown.
    new_json = json.dumps(obj, ensure_ascii=False, indent=2)
    new_asst = (
        asst_content[: json_match.start()]
        + "```json\n"
        + new_json
        + "\n```"
        + asst_content[json_match.end():]
    )

    # Sync the visible "Step 2 - ASSESS" line so the prose matches the JSON.
    new_asst = ASSESS_LINE_RE.sub(
        lambda m: f"{m.group(1)}{len(patterns)} pattern(s) detected, risk level: {risk}.",
        new_asst,
        count=1,
    )

    new_rec = dict(rec)
    new_rec["messages"] = [
        msgs[0],
        msgs[1],
        {"role": "assistant", "content": new_asst},
    ]
    return new_rec, fixes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=Path("data/synthetic/train_chat.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/synthetic/train_chat.fixed.jsonl"))
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found.")
        return 1

    counts: dict[str, int] = {}
    total = 0
    changed = 0
    with args.input.open("r", encoding="utf-8") as src, args.output.open("w", encoding="utf-8") as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            total += 1
            rec = json.loads(line)
            fixed_rec, fixes = fix_record(rec)
            if fixes:
                changed += 1
                for f in fixes:
                    counts[f] = counts.get(f, 0) + 1
            dst.write(json.dumps(fixed_rec, ensure_ascii=False) + "\n")

    print(f"[fix_train_labels] scanned {total} records")
    print(f"[fix_train_labels] modified {changed} records")
    for fix, n in sorted(counts.items()):
        print(f"  {fix:>40}: {n}")
    print(f"[fix_train_labels] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
