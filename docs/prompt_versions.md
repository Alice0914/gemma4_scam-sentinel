# Prompt Version History

Evaluation set: 70 hand-labeled real samples (30 FTC scam + 30 normal + 10 edge cases)

| Version | F1 | FPR | Key change |
|---|---|---|---|
| v1 baseline | 75.9% | 88% | 7 pattern definitions only — no few-shot examples, no SAFE rule |
| v2 improved | 81.8% | 80% | Added 6 few-shot examples (critical/high/medium/low/safe×2) and a CONTROL CLASS explainer |
| v3 SAFE rule | 83.3% | 72% | Added an explicit "SAFE BY DEFAULT RULE" — output safe whenever no specific phrase can be quoted |

---

## v1 → v2 changes
- Added 6 few-shot examples covering each risk level
- Added a CONTROL CLASS — NORMAL section with examples like "Mom, can you send $20"
- Clarified that urgency alone is NOT a scam signal

## v2 → v3 changes
- Made the **SAFE BY DEFAULT RULE** explicit:
  - "If you cannot directly quote a specific phrase, you must output safe"
  - Generic descriptions ("mentions payment") are not sufficient grounds to flag
- Added a list of always-safe categories (ride-share, pharmacy alerts, delivery status, etc.)
- Added a domain-distinction example (chase.com vs chase-secure-verify.com)

## Current file
- `backend/prompts/system_prompt.md` = **v3** (latest)
