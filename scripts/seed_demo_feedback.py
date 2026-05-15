"""
Seed demo feedback for Loop A (Constitutional Self-Critique).

Sends a curated set of BORDERLINE-NORMAL messages through the live backend
(`/analyze/text`) and, whenever the system mis-classifies one as risky,
auto-clicks 👎 via `/feedback` so that `data/user_feedback.jsonl` accumulates
the false-alarm signal that Loop A needs to operate on.

Run with the backend already serving on http://127.0.0.1:8000:

    python scripts/seed_demo_feedback.py
    python scripts/seed_demo_feedback.py --backend http://127.0.0.1:8000 --extra-correct

By design, every scenario in `SCENARIOS` is BENIGN. If the model flags any of
them as non-safe, that is a false positive — exactly the kind of data the
self-critique loop is built to fix.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

# Windows console defaults to cp1252; force UTF-8 so emoji in help/log lines
# don't blow up with UnicodeEncodeError.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_BACKEND = "http://127.0.0.1:8000"
FEEDBACK_PATH   = Path("data/user_feedback.jsonl")


# ── Borderline scenarios ─────────────────────────────────────────────────────
# Each looks superficially scammy (urgency, money request, secrecy) but is
# actually a benign message a real family member or coworker might send.
# Ground truth: every one of these should be classified `safe` or at worst `low`.

SCENARIOS: list[dict] = [
    {
        "label": "Family — small wire to new student account",
        "text": (
            "Dad, can you wire $300 to my new student account by tomorrow? "
            "I lost my card and tuition portal closes Friday. "
            "I'll pay you back from my paycheck on the 15th."
        ),
        "channel": "sms",
    },
    {
        "label": "Family — dying phone Uber money",
        "text": (
            "Mom, my phone is dying — can you Venmo me $50 for the Uber home tonight? "
            "I'm at @sarah-kim-99. Will pay you back tomorrow morning."
        ),
        "channel": "sms",
    },
    {
        "label": "Family — airport lost wallet",
        "text": (
            "Hi Mom, I'm at LAX and lost my wallet. Can you send $200 to my Venmo @jake-miller22 "
            "so I can grab a hotel tonight? Already cancelled the cards, just need cash for tonight."
        ),
        "channel": "sms",
    },
    {
        "label": "Family — surprise party secrecy",
        "text": (
            "Hey Mom, don't tell Dad — I'm planning his 60th surprise party. "
            "Can you send $150 to the bakery for the cake order? Their account is the same one "
            "you used last year for Sarah's birthday."
        ),
        "channel": "sms",
    },
    {
        "label": "Family — Sunday rent help",
        "text": (
            "Dad, can you send me $40 for groceries? I'll pay you back when I see you Sunday. "
            "My Venmo is @jake-miller22"
        ),
        "channel": "sms",
    },
    {
        "label": "Work — colleague meeting rescheduling with urgency",
        "text": (
            "Hi team, urgent — I need everyone to confirm by end of day that you can move "
            "tomorrow's standup to 8 AM. Client meeting got pulled forward. Reply ASAP."
        ),
        "channel": "email",
    },
    {
        "label": "Service — package shipping legit",
        "text": (
            "USPS: Your package #9405511234 has shipped and will arrive Friday. "
            "Track at usps.com/tracking — no action required."
        ),
        "channel": "sms",
    },
]


# Optionally: include real scams so 👍 (correct) feedback also accumulates,
# which Loop B (DPO) will need later. Only used when --extra-correct is passed.
SCAM_CONFIRMATIONS: list[dict] = [
    {
        "label": "Real scam — grandparent",
        "text": (
            "Grandma, it's me Tyler. I got into a car accident and need $1,500 right now. "
            "Don't tell Mom. Send to this new account."
        ),
        "channel": "voice",
    },
    {
        "label": "Real scam — Chase phish",
        "text": (
            "Chase Alert: Unusual activity detected. Verify immediately at "
            "chase-secure-verify.com/login to prevent suspension."
        ),
        "channel": "sms",
    },
]


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def analyze(backend: str, text: str, channel: str) -> dict:
    endpoint = f"{backend}/analyze/voice" if channel == "voice" else f"{backend}/analyze/text"
    body = (
        {"transcript": text, "metadata": {"channel": "voice"}}
        if channel == "voice"
        else {"text": text, "channel": channel, "metadata": None}
    )
    resp = requests.post(endpoint, json=body, timeout=600)
    resp.raise_for_status()
    return resp.json()


def submit_feedback(backend: str, *, text: str, channel: str, result: dict, verdict: str) -> None:
    body = {
        "input_text": text,
        "channel": channel,
        "predicted_risk": result.get("risk_level", "safe"),
        "predicted_patterns": result.get("patterns", []),
        "tool_calls": result.get("tool_calls", []),
        "user_verdict": verdict,
        "user_message_excerpt": (result.get("user_message") or "")[:200],
    }
    resp = requests.post(f"{backend}/feedback", json=body, timeout=30)
    resp.raise_for_status()


# ── Main ─────────────────────────────────────────────────────────────────────

def count_feedback(path: Path) -> dict[str, int]:
    counts = {"total": 0, "false_alarm": 0, "correct": 0}
    if not path.exists():
        return counts
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            counts["total"] += 1
            v = row.get("user_verdict")
            if v in counts:
                counts[v] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Loop A demo feedback")
    parser.add_argument("--backend", default=DEFAULT_BACKEND,
                        help="FastAPI base URL (default %(default)s)")
    parser.add_argument("--extra-correct", action="store_true",
                        help="Also send real scams + 👍 feedback to balance the file for Loop B")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print predictions only, do not POST any feedback")
    args = parser.parse_args()

    # Probe backend
    try:
        requests.get(f"{args.backend}/health", timeout=5).raise_for_status()
    except Exception as e:
        print(f"[seed] backend not reachable at {args.backend}: {e}")
        print("[seed] start it with: python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000")
        return 1

    before = count_feedback(FEEDBACK_PATH)
    print(f"[seed] backend OK at {args.backend}")
    print(f"[seed] feedback file before: total={before['total']} "
          f"false_alarm={before['false_alarm']} correct={before['correct']}")

    n_false_alarms_added = 0
    n_correct_added      = 0
    n_safe_skipped       = 0

    # Pass 1: borderline-normal scenarios — expect them to be "safe"; any
    # non-safe prediction is a false alarm → 👎
    for i, scn in enumerate(SCENARIOS, 1):
        print(f"\n[seed] [{i}/{len(SCENARIOS)}] {scn['label']}")
        print(f"        channel={scn['channel']}, len={len(scn['text'])}")
        t0 = time.time()
        try:
            result = analyze(args.backend, scn["text"], scn["channel"])
        except Exception as e:
            print(f"        analyze failed: {e}")
            continue
        risk = result.get("risk_level", "?")
        patterns = result.get("patterns", [])
        dt = time.time() - t0
        print(f"        -> risk={risk}, patterns={patterns}, {dt:.1f}s")

        if risk == "safe":
            n_safe_skipped += 1
            print("        OK (no false alarm to record)")
            continue

        if args.dry_run:
            print("        [dry-run] would POST 👎 false_alarm")
            continue

        try:
            submit_feedback(
                args.backend,
                text=scn["text"],
                channel=scn["channel"],
                result=result,
                verdict="false_alarm",
            )
            n_false_alarms_added += 1
            print("        👎 false_alarm recorded")
        except Exception as e:
            print(f"        feedback POST failed: {e}")

    # Pass 2 (optional): real scams — expect non-safe; 👍 the correct catches
    if args.extra_correct:
        for i, scn in enumerate(SCAM_CONFIRMATIONS, 1):
            print(f"\n[seed] [+{i}/{len(SCAM_CONFIRMATIONS)}] {scn['label']}")
            t0 = time.time()
            try:
                result = analyze(args.backend, scn["text"], scn["channel"])
            except Exception as e:
                print(f"        analyze failed: {e}")
                continue
            risk = result.get("risk_level", "?")
            dt = time.time() - t0
            print(f"        -> risk={risk}, {dt:.1f}s")
            if risk == "safe":
                print("        unexpected: model said safe on a real scam, skipping 👍")
                continue
            if args.dry_run:
                print("        [dry-run] would POST 👍 correct")
                continue
            try:
                submit_feedback(
                    args.backend,
                    text=scn["text"],
                    channel=scn["channel"],
                    result=result,
                    verdict="correct",
                )
                n_correct_added += 1
                print("        👍 correct recorded")
            except Exception as e:
                print(f"        feedback POST failed: {e}")

    after = count_feedback(FEEDBACK_PATH)
    print("\n" + "=" * 60)
    print("[seed] DONE")
    print(f"[seed] borderline scenarios run:    {len(SCENARIOS)}")
    print(f"[seed]   classified safe (good):    {n_safe_skipped}")
    print(f"[seed]   false alarms recorded 👎:  {n_false_alarms_added}")
    if args.extra_correct:
        print(f"[seed] real scams sent:             {len(SCAM_CONFIRMATIONS)}")
        print(f"[seed]   correct catches 👍:        {n_correct_added}")
    print(f"[seed] feedback file: total {before['total']} -> {after['total']} "
          f"(+{after['total'] - before['total']})")
    print(f"[seed]   false_alarm: {before['false_alarm']} -> {after['false_alarm']}")
    print(f"[seed]   correct:     {before['correct']} -> {after['correct']}")
    print()
    if after["false_alarm"] >= 3:
        print("[seed] ✓ enough false alarms to run Loop A:")
        print("        python scripts/self_critique.py            # dry-run")
        print("        python scripts/self_critique.py --apply    # promote winner")
    else:
        print(f"[seed] need ≥3 false_alarm rows for a meaningful Loop A run; have {after['false_alarm']}")
        print("        re-run this script, or click 👎 manually in the UI")

    return 0


if __name__ == "__main__":
    sys.exit(main())
