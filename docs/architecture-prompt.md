# Scam Sentinel — Full Architecture & Workflow (Prompt-Ready)

> Use this document as a single self-contained prompt to brief any LLM, contributor, or judge on the entire system. It covers what the product is, every runtime stage, every data file, the 12 protective tools, and the Self-Improving Cascade feedback loop.

---

## 0. Identity (the one sentence)

**Scam Sentinel is not a final forensic deepfake detector. It is a multimodal scam-risk assistant that combines phone call transcript analysis, conversation patterns, retrieved real cases, and verification workflows — and improves itself from user feedback.**

For every suspicious input it answers four questions in plain language a 70-year-old or 20-year-old can act on in 5 seconds:

1. Is this whole situation a scam?
2. Why is it dangerous?
3. What should I do right now?
4. How do I verify with my family?

---

## 1. System overview (one-screen map)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  USER INPUT  (SMS / Email / Voice transcript / MMS image OCR)           │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
                ┌──────────────▼──────────────┐
                │ FastAPI  /analyze/{text|voice}                         │
                └──────────────┬──────────────┘
                               │
        ┌──────────────────────▼──────────────────────┐
        │ STAGE 1 — Fast Triage (Gemma 3 4B)          │  ~1 s
        │  • prompts/fast_classifier.md               │
        │  • returns ONLY risk_level                  │
        │  • if "safe" → short-circuit, skip Stage 2  │
        └──────────────────────┬──────────────────────┘
                               │ (non-safe only)
        ┌──────────────────────▼──────────────────────┐
        │ STAGE 2 — Deep Reasoner (Gemma 4 9B)        │  ~10–30 s
        │  • prompts/system_prompt.md (v3 SAFE rule)  │
        │  • optional RAG: ChromaDB top-3 cases       │
        │  • 5-step Chain-of-Thought                  │
        │  • emits JSON: risk_level + patterns +      │
        │    user_message + tool_calls                │
        └──────────────────────┬──────────────────────┘
                               │
        ┌──────────────────────▼──────────────────────┐
        │ TOOL DISPATCH — 12 tools (6 core + 6 chan)  │
        │  rule-based fallback fills missing tool_calls│
        └──────────────────────┬──────────────────────┘
                               │
        ┌──────────────────────▼──────────────────────┐
        │ FRONTEND — iPhone-style Phone Emulator      │
        │  • warning overlay + action buttons          │
        │  • Step-by-step CoT panel                    │
        │  • 👍 / 👎 FEEDBACK BUTTONS  (lucide-react)  │
        └──────────────────────┬──────────────────────┘
                               │ feedback POST
        ┌──────────────────────▼──────────────────────┐
        │ SELF-IMPROVING CASCADE                       │
        │  data/user_feedback.jsonl                    │
        │   ├─► Constitutional Self-Critique (daily)  │
        │   │     Gemma 4 reads false-positives,       │
        │   │     proposes new system_prompt,          │
        │   │     auto A/B against eval_set.jsonl,     │
        │   │     promotes winning prompt.             │
        │   └─► DPO Preference Pairs (weekly/manual)   │
        │         👎 samples → preference dataset →    │
        │         Colab L4 4-bit QLoRA DPO →           │
        │         LoRA adapter swapped in at runtime.  │
        └─────────────────────────────────────────────┘
```

---

## 2. Data assets (current verified counts, 2026-05-10)

| File | Count | Purpose |
|---|---|---|
| `data/seeds.jsonl` | 80 | Hand-written seed examples, 8 categories × 10 |
| `data/seeds_real.jsonl` | 571 | Real UCI SMS Spam, classified into the same 8 categories |
| `data/synthetic/raw.jsonl` | 1,112 | Gemma 4 expansion of hand-written seeds (×13) |
| `data/synthetic/raw_real.jsonl` | 2,224 | Gemma 4 expansion of real UCI spam (×4) |
| `data/synthetic/combined.jsonl` | 3,907 | Raw union before filtering |
| `data/synthetic/train.jsonl` | **3,100** | Filtered, deduped, 80% stratified — for optional fine-tuning |
| `data/synthetic/dev.jsonl` | **771** | Filtered, 20% stratified — for early-stopping / HP selection |
| `data/evaluation/eval_set.jsonl` | **300** | Real hand-labeled, **never touched in training** — primary metric source |
| `data/evaluation/eval_set_70.jsonl` | 70 | Archived snapshot of the original evaluation set |
| `data/rag_cases.jsonl` | 117 | Real FTC/APWG cases (target: 150–200, currently below) |
| `data/vector_store/` | (ChromaDB) | Persistent vector index of `rag_cases.jsonl` |
| `data/user_feedback.jsonl` | (new, runtime) | 👍/👎 events for Self-Improving Cascade |

8 scam categories: `family_impersonation, prosecutor_scam, bec_scam, romance_scam, package_scam, bank_phishing, phishing_link, normal`.

---

## 3. Runtime workflow (step by step)

### Step A — Frontend submit
[`frontend/app/page.tsx`](../frontend/app/page.tsx) POSTs to `localhost:8000`:
- `/analyze/text` for SMS / email / chat
- `/analyze/voice` for call transcripts (+ optional voice_signals dict)

### Step B — FastAPI dispatch
[`backend/main.py`](../backend/main.py) wraps the payload in a `SignalInput` pydantic model and calls `agent.analyze(signals, use_self_consistency=False)`.

### Step C — Stage 1: Fast classifier (Gemma 3 4B)
[`backend/reasoning_agent.py::_fast_classify`](../backend/reasoning_agent.py)
- Loads compact prompt `backend/prompts/fast_classifier.md`
- 1 Ollama call, `temperature=0.1`, `num_predict=64`
- Returns `{"risk_level": <safe|low|medium|high|critical>}`
- **If `safe`** → short-circuit, return canned "looks normal" response. **No Gemma 4 call.** This is the speed win.

### Step D — RAG retrieval (currently disabled by default)
[`backend/rag.py::ScamCaseRetriever.retrieve`](../backend/rag.py)
- ChromaDB `PersistentClient` over `data/vector_store/`
- Embedder: ChromaDB default (`all-MiniLM-L6-v2` ONNX, 384-d, unit-normalized)
- Distance: L2 by default (= cosine-equivalent ranking under unit-norm)
- Returns top-3 cases injected as a `SIMILAR PAST CASES` block in the user message
- **Disabled in production** because the 300-sample eval showed it inflated FPR (33.1% → 58.9%). Re-enable only after the index is balanced across normal/scam categories.

### Step E — Stage 2: Deep reasoner (Gemma 4 9B)
[`backend/reasoning_agent.py::_call_ollama`](../backend/reasoning_agent.py)
- Loads `backend/prompts/system_prompt.md` (v3, SAFE-by-default rule)
- `num_gpu=20, num_ctx=4096` (partial offload — 9 GB Q4_K_M does not fit fully on RTX 4060 Ti 8 GB)
- Forces 5-step Chain-of-Thought before final JSON:
  - Step 1 — IDENTIFY which of the 7 patterns appear
  - Step 2 — ASSESS overall risk_level
  - Step 3 — EXPLAIN each pattern in plain language
  - Step 4 — DECIDE which of the 12 tools to call
  - Step 5 — ANSWER FOUR QUESTIONS in `user_message`
- Optional self-consistency: 3× temperature 0.3, majority vote. **Off by default for demo latency.**

### Step F — JSON extraction + guardrails
[`backend/reasoning_agent.py::_extract_json` / `_normalize_parsed`](../backend/reasoning_agent.py)
- Tries ```` ```json ```` block → bare `{...}` → keyword fallback
- Pattern-count guardrail: 2+ text-scanned patterns → at least `medium`, 3+ → at least `high`
- Risk-level whitelist enforcement: must be one of `safe|low|medium|high|critical`

### Step G — Tool inference fallback
[`backend/reasoning_agent.py::_infer_tool_calls`](../backend/reasoning_agent.py)
If model returned `risk ≥ medium` but no `tool_calls`, deterministic rules fill them based on:
- risk_level → `create_incident_report`, `notify_trusted_contact`
- `impersonation` → `suggest_callback`, `generate_secret_question` (voice only)
- `urgency` / `new_account` → `start_wait_timer`, `block_payment_intent`
- channel-specific → `block_phone_number` / `block_email_sender`
- URL match → `check_url_safety`
- brand keyword → `show_official_contact`
- OCR text in metadata → `verify_image_message`
- always for medium+ → `flag_red_phrases`

### Step H — Tool execution
[`backend/tools.py::execute_tool_call`](../backend/tools.py) dispatches through `TOOL_REGISTRY` (12 tools). Each returns `ToolResult { tool_name, success, data { …, ui_action, ui_message } }`.

### Step I — Frontend rendering
[`frontend/app/components/PhoneEmulator.tsx`](../frontend/app/components/PhoneEmulator.tsx) and [`AnalysisPanel.tsx`](../frontend/app/components/AnalysisPanel.tsx):
- Phone shell with channel-aware screen (SMS app / Mail app / incoming-call)
- Result overlay slides up; each tool card driven by `ui_action`
- Right panel streams the model's CoT reasoning (Steps 1–5)
- **NEW**: feedback section at the bottom — `<ThumbsUp />` / `<ThumbsDown />` from `lucide-react`

### Step J — Feedback capture (Self-Improving Cascade entry point)
On 👍/👎 click → POST `/feedback` to FastAPI → append a JSONL line to `data/user_feedback.jsonl`:
```json
{
  "timestamp": "2026-05-10T14:32:11Z",
  "session_id": "...",
  "input_text": "...",
  "channel": "sms",
  "predicted_risk": "high",
  "predicted_patterns": ["urgency", "new_account"],
  "tool_calls": [...],
  "user_verdict": "correct" | "false_alarm",
  "user_message_excerpt": "..."
}
```

---

## 4. The 12 protective tools

**Core 6 (verification & response)** — `backend/tools.py`
1. `notify_trusted_contact` — push alert to a registered family member
2. `suggest_callback` — recommend the saved real number
3. `generate_secret_question` — verification question only the real person knows
4. `start_wait_timer` — 2-minute cool-down on money transfer
5. `create_incident_report` — save analyzed conversation to history
6. `block_payment_intent` — hard gate on payment links

**Channel-specific 6 (defense)**
7. `block_phone_number` — device blocklist + fraud report
8. `block_email_sender` — auto Gmail spam filter
9. `check_url_safety` — lookalike-domain detection (e.g. `paypa1`, `chase-secure.xyz`)
10. `verify_image_message` — OCR text re-analyzed by the same detector
11. `show_official_contact` — real phone/website of the impersonated brand
12. `flag_red_phrases` — highlight specific dangerous phrases in the original message

---

## 5. Models & evaluation (final, 300-sample real test set)

| Setup | Accuracy | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| **gemma3:4b / v3 / no RAG** ✅ production | **80.3%** | 68.1% | 99.2% | **80.8%** | **33.1%** |
| gemma3:4b / v3 / + RAG | 65.7% | 54.8% | 100.0% | 70.8% | 58.9% |
| gemma4 9B / v3 / no RAG | 53.0% | 46.9% | 97.6% | 63.4% | 78.9% |

Production cascade: Gemma 3 4B for triage (safe → done), Gemma 4 9B for explanation + tool calls when non-safe. RAG disabled.

Weights are pre-trained and **unchanged** — no fine-tuning has been executed. `train.jsonl` (3,100) and `dev.jsonl` (771) are prepared but not consumed. LoRA fine-tuning is a **future Track B**, gated on Day 11 conditions; planned for Colab Pro L4 with 4-bit QLoRA via Unsloth.

---

## 6. Self-Improving Cascade (the differentiator)

### 6.1 Loop A — Constitutional Self-Critique (lightweight, frequent)

**Trigger**: nightly cron, or manually via `scripts/self_critique.py`

```
1. Read last N entries of data/user_feedback.jsonl where user_verdict = "false_alarm".
2. For each entry, prompt Gemma 4 with:
     "The system flagged this message as <risk>. The user marked it as a
      false alarm. Here is the current system prompt. Propose a minimal
      revision (≤3 lines diff) that would still catch real scams of this
      shape but not this benign message. Show only the diff."
3. Apply each proposed diff to a candidate prompt → save as system_prompt_candidate.md.
4. Run scripts/evaluate.py on data/evaluation/eval_set.jsonl with both prompts.
5. If candidate F1 ≥ current F1 AND candidate FPR ≤ current FPR:
     promote candidate → backend/prompts/system_prompt.md
     bump prompt version (v3 → v4 → v5 …)
     log the diff in docs/prompt_versions.md
   Otherwise: discard, log the attempt.
```

No weight changes. No GPU. Runs in ~5 minutes. Improves the system every time a user clicks 👎.

### 6.2 Loop B — DPO Preference Pairs (heavy, periodic)

**Trigger**: weekly, or when `user_feedback.jsonl` accumulates ≥ 200 👎 + ≥ 200 👍

```
1. scripts/build_dpo_pairs.py
     For each 👎 entry:  chosen = "safe / no-action JSON"
                         rejected = the actual model output that day
     For each 👍 entry:  chosen = the actual output
                         rejected = a synthetic "safe / no-action" alternative
   → data/dpo_pairs.jsonl

2. Colab Pro L4, 4-bit QLoRA + DPOTrainer (TRL):
     base: gemma3:4b  (production classifier)
     LoRA r=16, alpha=32, target=q/k/v/o
     1–2 epochs, β=0.1, lr=5e-6
   → models/gemma3-4b-scam-dpo-adapter/

3. Evaluate adapter on data/evaluation/eval_set.jsonl.
   If F1 ↑ AND FPR ↓ vs current production:
     ship adapter; Ollama loads base + adapter at startup.
   Otherwise: archive, keep current.
```

The base weights are never touched. Only the LoRA adapter is swapped in. Rollback is instant.

### 6.3 Why both, not either

| Loop | Cost | Cadence | Fixes |
|---|---|---|---|
| Constitutional | minutes, no GPU | daily | shallow / pattern-level errors |
| DPO | hours, GPU | weekly | deep calibration bias (e.g. gemma4's "money → low risk" prior) |

Constitutional handles the long tail of small prompt issues. DPO handles structural calibration. Together they form a continuous improvement flywheel that does not require human prompt engineering between releases.

---

## 7. Repo layout (truth)

```
scam-sentinel/
├── CLAUDE.md                          source of truth for design
├── README.md                          public-facing
├── docs/
│   ├── architecture-prompt.md         ← this file
│   ├── eval_results.md                full eval methodology
│   ├── prompt_versions.md             v1 → v2 → v3 history
│   └── colab-finetuning-guide.md      Colab Pro L4 step-by-step
├── backend/
│   ├── main.py                        FastAPI app, /analyze/* + /feedback
│   ├── reasoning_agent.py             Gemma 3 + Gemma 4 cascade
│   ├── tools.py                       12 protective tools
│   ├── rag.py                         ChromaDB retriever
│   └── prompts/
│       ├── fast_classifier.md         Gemma 3 prompt
│       ├── system_prompt.md           Gemma 4 prompt (v3)
│       └── synthesis.md               synthetic-data prompt
├── frontend/app/
│   ├── page.tsx
│   └── components/
│       ├── PhoneEmulator.tsx          iPhone shell + result overlay + 👍/👎
│       └── AnalysisPanel.tsx          CoT reasoning panel
├── data/
│   ├── seeds.jsonl (80)
│   ├── seeds_real.jsonl (571)
│   ├── synthetic/ (train 3,100 / dev 771 / raw etc.)
│   ├── evaluation/ (eval_set 300, eval_set_70 70)
│   ├── rag_cases.jsonl (117)
│   ├── vector_store/                  ChromaDB persistent index
│   └── user_feedback.jsonl            ← Self-Improving Cascade input
└── scripts/
    ├── generate_synthetic.py
    ├── extract_real_seeds.py
    ├── filter_quality.py
    ├── expand_eval_set.py
    ├── evaluate.py
    ├── self_critique.py               (Loop A, to add)
    ├── build_dpo_pairs.py             (Loop B, to add)
    ├── prepare_finetune_data.py
    └── train_lora.py
```

---

## 8. North-star check

Every architectural choice — pre-trained Gemma over fine-tuning, hybrid cascade over a single model, plain-language reasoning over scores, function calling over passive warnings, Self-Improving Cascade over static deployment — serves to prove the one sentence at the top.

If a proposed feature cannot trace back to that sentence, it does not ship.
