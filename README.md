# Scam Sentinel — Stop the Next Victim

## TL;DR

- **Scam Sentinel is an on-device panic-interruption system for scam prevention.**
- It uses a **fine-tuned Gemma 4 E2B** model to analyze SMS, email, voice-call transcripts, and MMS image text **locally**.
- When risk is high, it **takes over the full phone screen**, explains the danger in plain language, and calls a curated set of protective tools — block this caller, alert a trusted contact, ask a verification question, start a 2-minute wait timer. The model emits the tool calls; on a real phone the OS executes them, in the demo the UI surfaces them as the protective steps the user should take.
- The fine-tuned model achieves **98.0% precision** and reduces **false positives to 1.1%** on a 300-sample real-world evaluation set.
- The goal is simple: **stop the user before they panic-click, panic-reply, or panic-send money.**

> *"Scammers don't need your password. They need your panic."*
> Scam Sentinel takes over the screen, slows the clock, and gives the user back the seconds they need to think.

---

## Why this wins — four dimensions in one project

Scam Sentinel is built to satisfy **four winning frames simultaneously**, not pick one:

| Dimension | What Scam Sentinel proves |
|---|---|
| 🎯 **Product impact** | Tackles a problem where older adults and vulnerable populations actually lose money — **$2.9 B from Americans 60+ in 2024 (FTC)**, **$10 B total**, **$1 T+ globally**. Targets the demographic least likely to install paid cloud protection. |
| 🧠 **Technical depth** | QLoRA fine-tune of **Gemma 4 E2B** via Unsloth + TRL. Drives F1 from **58.0 → 86.1** and **FPR from 97.7% → 1.1%** vs. the same-size base — a **+28.1 F1 pt** gain and **88× FPR reduction** on a 300-sample real-world test set. Full reproducible pipeline: Colab L4 SFT → WSL2 merge → llama.cpp GGUF → Ollama Hub. |
| 🛡️ **Safety & Trust** | **All analysis is on-device.** Sensitive messages, voice transcripts, emails, and image text never leave the phone. No cloud account, no API key, no signal required. Every verdict is grounded with the exact phrases that triggered it; limits are documented openly. Saved-contact messages are not auto-scanned — only flagged on user request or (roadmap) on stylometric drift, the SIM-swap / hijacked-account second-opinion path. |
| 📱 **Real-world UX** | In a high-risk situation, Scam Sentinel does not show a small banner — it executes a **full-screen intervention** that physically replaces the scammer's call-to-action with the protective one (Hang up · Block sender · Notify family · 2-min wait timer). The interrupt is the product. |

This project competes across **three tracks at once** — **Main Track** (best overall), **Safety & Trust Impact Track** (transparent, grounded, explainable AI), and the **Special Technology Tracks** (Ollama, Unsloth, llama.cpp).

### Links

- 🎬 **3-minute demo video (YouTube)**: <https://youtu.be/nOHGK9eKe3w>
- 💻 **Code repository**: <https://github.com/Alice0914/gemma4_scam-sentinel>
- 🤖 **LoRA adapter (HuggingFace)**: <https://huggingface.co/Alice0914/gemma4-e2b-scam-sentinel>
- 📦 **Quantized model (Ollama Hub)**: <https://ollama.com/alicek0914/gemma4-scam>

> **This is not a final forensic deepfake detector. It is a multimodal scam risk assistant that combines phone-call transcript analysis, conversation patterns, and verification workflows.**

---

## What it does

For every suspicious input, Scam Sentinel answers four questions:

1. **Is this whole situation a scam?**
2. **Why is it dangerous?**
3. **What should I do right now?**
4. **How do I verify with my family?**

Output is structured: a risk level, a plain-language explanation, the scam patterns detected, and a list of concrete protective steps the model recommends via function calling. On a real mobile deployment the OS would carry out these steps automatically; in the current demo the UI surfaces them as a checklist of what the model wants done.

---

## Architecture at a glance

![Scam Sentinel system overview](docs/diagrams/Scam_Sentinel_System_Overview.png)

### How a single request flows

1. **Client (iPhone emulator UI)** — the user receives an SMS, email, MMS image, or live phone call inside the in-browser phone shell. Five pre-built scenarios cover the common scam shapes (live audio call, BEC wire, Chase phish, image smishing, normal family message).
2. **FastAPI backend** routes the request to the right endpoint:
   - `POST /analyze/text` — SMS / email
   - `POST /analyze/image` — MMS image (runs `pytesseract` OCR on the upload first)
   - `POST /analyze/voice_full` — full call audio, SHA-256 cached so re-runs of the same clip are instant
   - `POST /feedback` — async 👍 / 👎 event log (the UI also shows a 🤷 'Not sure' option, which dismisses the prompt without logging anything — no signal, no noise)
3. **Pre-processing** — for voice, Whisper-base STT (≈ 150 MB) transcribes audio → text + per-sentence timestamps. It stays loaded on the same GPU as the reasoner so there is no model swap cost.
4. **Reasoning (GPU)** — every request lands on **the same model**: fine-tuned Gemma 4 E2B + QLoRA, merged into the base and quantized to Q4_K_M GGUF (3.2 GB), served locally via Ollama as `gemma4-scam`. F1 86.1% / FPR 1.1% on the 300-sample real test set. 
5. **Action Layer — 12 protective tool calls** — the model emits structured JSON containing `risk_level`, `patterns[]`, a plain-language `user_message`, and a curated subset of 12 tool calls (6 verification + 6 channel defense). These are Gemma 4's *recommendations* — on a real mobile deployment the OS executes them (call blocklist, payment-app intercept, contacts push); in this demo the UI renders them as a checklist of "protective steps to take" so the user always knows what the model thinks should happen next.
6. **Feedback path** — every verdict gets a 👍 / 👎 button. Events stream back to `/feedback` and feed the Self-Improving Cascade below.

All inference runs on the user's local GPU. User content — message text, voice transcripts, OCR-extracted image text — never leaves the machine at runtime; the only thing that crosses the network is the model weights themselves, and only once at install time (ollama pull).

---

## How it learns from feedback (Self-Improving Cascade)

![Self-Improving Cascade — feedback loops](docs/diagrams/Self_improving_Cascade.png)

Every 👍 / 👎 event is appended to `data/user_feedback.jsonl`. Two independent loops consume that store and produce promotable artifacts. **Both loops gate every promotion against the same real evaluation set** — Loop A defaults to a 50-sample stratified subset for fast iteration (`--full` switches to the entire 300), Loop B uses the full 300 via `scripts/evaluate.py`. A regression never reaches production.

### Loop A — Constitutional Self-Critique *(prompt-level)*

Operates at the prompt layer; no retraining required, so the turnaround is hours not days.

1. **Trigger** — manual via `python scripts/self_critique.py --apply` (schedulable via cron once a feedback cadence is established).
2. **Review** — Gemma 4 reads recent `false_alarm` events whose predicted risk was NOT `safe` (the only ones that came out of the deep reasoner) and identifies which prompt rule each one violated.
3. **Propose** — emits a revised `backend/prompts/system_prompt.md` (typically a tightening of the SAFE-by-default rule or a new always-safe category).
4. **A/B gate** — both the current and proposed prompts run against `data/evaluation/eval_set.jsonl` (defaults to a 50-sample stratified subset for ~5-minute turnaround; `--full` uses the entire 300 hand-labeled samples).
5. **Promote** — only if F1 does not regress AND FPR **strictly decreases**. Promoted artifact: `backend/prompts/system_prompt.md`.

### Loop B — DPO Preference Tuning *(weights-level)*

Operates on the model weights themselves; produces a new LoRA adapter when enough feedback has accumulated.

1. **Trigger** — manual / weekly, once enough 👍 + 👎 events have accumulated to make a meaningful training set.
2. **Build preference pairs** — `scripts/build_dpo_pairs.py` converts the feedback log into (prompt, chosen, rejected) triples:
   - `false_alarm` → **rejected** = the over-flagged response, **chosen** = a synthesized SAFE response. Teaches: stop yelling on normal messages.
   - `correct` with risk ≥ medium → **chosen** = the correct flagged response, **rejected** = synthesized "missed it" silence. Teaches: stop going silent on real scams.
3. **Train DPO adapter** — `scripts/train_dpo.py` runs in WSL2 on the GPU using `trl.DPOTrainer` + Unsloth's `PatchDPOTrainer()` for the fast kernels (β = 0.1, lr = 5e-6, LoRA r = 16, starting from the published SFT adapter).
4. **Evaluation gate (manual today)** — run `scripts/evaluate.py` against the 300-sample test set; promote only if F1 ↑ AND FPR ↓. (The trainer saves the adapter unconditionally; the gate lives outside the training script so the trained artifact is preserved even when it fails the bar.)
5. **Ship** — merge LoRA → bf16 safetensors → GGUF f16 → Q4_K_M, then `ollama create gemma4-scam:dpo` (identical pipeline to the initial SFT deployment in [§Deploying the fine-tuned model](#deploying-the-fine-tuned-model-qlora--ollama)).

The two loops are deliberately decoupled: Loop A can ship fixes within hours when a new scam category emerges, while Loop B accumulates volume and ships a stronger model on a slower cadence.

---

## Finalized features

### 1. Multimodal input channels

| Channel | Status | What it does |
|---|---|---|
| 💬 SMS | ✅ | Text message analysis |
| 📧 Email | ✅ | Sender + content analysis (BEC, phishing) |
| 📞 Voice | ✅ | Live call transcription via Whisper-base STT, analyzed every 20 s |
| 📷 Image (MMS) | ✅ | OCR-extracted-text re-analysis |

### 2. Twelve protective tools (function calling)

Every Gemma 4 verdict at risk ≥ medium produces a curated subset of these 12 tool calls — each one a concrete protective step backed by a real-world action plan. The model emits the call; on a real mobile deployment the OS would execute it (CallKit / Messages blocklist, contacts push, payment-app intercept). In the current web demo the UI renders them as the protective steps the user should take next:

**Original 6:**
1. `notify_trusted_contact` — Push alert to a registered family member
2. `suggest_callback` — Recommend the saved number, not the incoming one
3. `generate_secret_question` — Verification question only the real family member knows
4. `start_wait_timer` — 2-minute cool-down before any money transfer
5. `create_incident_report` — Save analyzed conversation to history
6. `block_payment_intent` — Hard gate before any money transfer link

**Added during finalization:**
7. `block_phone_number` — Add to device blocklist + report (case ID returned)
8. `block_email_sender` — Auto-create Gmail filter for the sender
9. `check_url_safety` — Lookalike-domain detection + click-blocking popup
10. `verify_image_message` — OCR'd text re-analyzed with the same scam detector
11. `show_official_contact` — Real phone/website for the impersonated brand (Chase, USPS, IRS, Amazon, FedEx, UPS, PayPal, Wells Fargo, SSA, Bank of America)
12. `flag_red_phrases` — Highlight specific risky phrases inside the original message

### 3. Five demo scenarios (one-tap reproducible)

| Scenario | Channel | Tool calls Gemma 4 makes |
|---|---|---|
| 👴 Grandparent scam (live audio call) | voice | block_phone, callback, secret question, wait timer, flag phrases, notify family |
| 💼 BEC wire fraud | email | block_email, official_contact (Bank of America), block_payment, flag phrases |
| 🏦 Chase bank phish | sms | check_url, official_contact (Chase), block_phone |
| 📷 Image smishing (MMS) | sms | verify_image (OCR), check_url (FedEx-track.xyz), official_contact (FedEx) |
| ✅ Normal family message (saved contact "James (Son)") | sms | (no auto-scan — manual "Scan with Sentinel" only) |

### 4. Phone-emulator demo UI

- iPhone-style shell — bezel, Dynamic Island, home indicator, iOS status bar with cellular / WiFi / battery SVG icons
- Four built-in text/email scenarios + a live audio-call scenario (left phone) with a paired analysis panel (right side) showing the verdict, detected patterns, protective tool calls, and the plain-language reason
- iOS-style notification banner that slides in from the top when a message "arrives"; soft pulse on the critical CTA buttons
- **Full-screen takeover when risk is high** — red gradient with the verdict, the patterns Gemma 4 detected, the protective steps it called for, and a single primary action button (e.g. 🛑 HANG UP NOW & BLOCK +1-555-0142)
- **Image-MMS handling** — chat-thread preview with the incoming image blurred behind a centered Sentinel modal that asks the user to confirm before pytesseract OCR + analysis run
- **Saved-contact messages** are surfaced with the contact name (e.g. "James (Son)") and are not auto-scanned; a manual "Scan with Sentinel" button covers the SIM-swap / hijacked-account edge case
- **Inline feedback panel** after every result ("Was this analysis helpful? 👍 / 🤷 / 👎") feeding the Self-Improving Cascade
- Right pane surfaces the structured output the model returned — risk level, detected patterns, protective tool calls, and the plain-language `user_message`

### 5. Reasoning architecture

- **Model**: Fine-tuned Gemma 4 E2B + QLoRA (`gemma4-scam`, Q4_K_M GGUF via Ollama) with system prompt v3 (SAFE-by-default rule)
- **Architecture**: Single-model — every request goes straight to the fine-tuned model (no Stage 1 cascade). The earlier `gemma3:4b` triage stage was retired after the QLoRA model reached F1 86.1% / FPR 1.1% on its own.
- **RAG**: ChromaDB index of 117 real FTC/APWG cases wired but **off by default** — the 300-sample evaluation showed RAG hurt on conversational ham (see Findings). Enabling it requires both setting `SCAM_SENTINEL_RAG=1` at startup *and* a built `data/vector_store/` index; `agent.analyze(..., use_rag=False)` is the API-level default. `GET /health` reports the live state.
- **Self-consistency**: 3-run majority vote available (disabled by default for demo speed)
- **Output cleaning**: User-facing `user_message` runs through a server-side cleaner that strips code fences, unpacks malformed JSON the model occasionally emits, and removes hallucinated non-Latin script characters.
- **Inference fallback**: Rule-based tool inference if the model omits `tool_calls` from JSON

### 6. Dataset & evaluation

| Set | Count | Source |
|---|---|---|
| Train (synthetic) | 3,100 | Hand-written seeds + UCI seeds × Gemma-generated variants |
| Dev (synthetic) | 771 | 20% stratified hold-out |
| **Test (real)** | **300** | 70 hand-labeled (FTC + custom edge cases) + 230 UCI samples (training-disjoint) |

Train/eval leakage explicitly prevented by excluding the 571 UCI seeds used in training.

---

## Evaluation results

All numbers below are measured on the same **300-sample real test set** — 70 hand-labeled (30 FTC scam + 30 normal + 10 edge) + 230 UCI SMS (150 ham + 80 spam, training-disjoint via the `seeds_real.jsonl` filter). The set is never touched during training.

### Final result — QLoRA fine-tune vs base models (3-way apples-to-apples)

Identical v3 system prompt, no RAG. The three rows differ only in base-model size and the presence of the fine-tuned LoRA adapter:

| Setup | Size | Accuracy | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|---|
| Gemma 4 E4B base (Ollama Q4_K_M) | ~8B | 53.0% | 46.9% | 97.6% | 63.4% | 78.9% |
| Gemma 4 **E2B base** (Ollama Q4_K_M) | ~5B | 41.7% | 41.4% | 96.8% | 58.0% | **97.7%** |
| **Gemma 4 E2B + QLoRA** ([Unsloth adapter](https://huggingface.co/Alice0914/gemma4-e2b-scam-sentinel)) ✅ production | ~5B | **89.7%** | **98.0%** | 76.8% | **86.1%** | **1.1%** |

**Key findings**

1. **Same-size apples-to-apples (E2B base → E2B + QLoRA)**: F1 jumps **+28.1 pt** (58.0 → 86.1), FPR collapses **88×** (97.7% → 1.1%), Precision more than doubles (41.4 → 98.0).
2. **Untuned Gemma 4 base is unusable for this task**: both E2B and E4B base models flag the vast majority of normal messages as suspicious (FPR 78.9% and 97.7%). The base instruction-tuned model has no domain prior for scam vs. normal text.
3. **Fine-tuning beats raw scale**: the fine-tuned 5B (E2B) model outperforms the larger 8B (E4B) base by +22.7 F1 points, while running on consumer-grade hardware (8 GB VRAM via Ollama Q4_K_M).
4. **Trade-off — recall**: 96.8% (E2B base) → 76.8% (fine-tuned). The design chooses precision-first calibration because every false alarm on a normal message destroys user trust; see "Design rationale" in the [HF model card](https://huggingface.co/Alice0914/gemma4-e2b-scam-sentinel). The Self-Improving Cascade DPO loop (Loop B, below) is the recall-recovery mechanism — every confirmed-miss flows back into the next adapter.

---

### How we got here — research history (interim baselines, pre-QLoRA)

Before the QLoRA model existed, we ran two earlier evaluation rounds on the same 300-sample set. The history is kept here because the negative findings (RAG hurts, Gemma 4 9B miscalibrates on conversational ham, the 70 → 300 sample expansion changes the verdict) are themselves load-bearing — they justify several current architectural choices (RAG off by default, single-model instead of cascade, 300-sample evaluation gate everywhere).

**Pre-QLoRA — 300-sample baseline (2026-05-06)**

| Setup | Accuracy | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| **gemma3:4b / v3 / no RAG** (best pre-QLoRA baseline) | **80.3%** | 68.1% | 99.2% | **80.8%** | **33.1%** |
| gemma3:4b / v3 / + RAG | 65.7% | 54.8% | 100.0% | 70.8% | 58.9% |
| gemma4 9B / v3 / no RAG | 53.0% | 46.9% | 97.6% | 63.4% | 78.9% |

Findings:

1. **gemma3:4b decisively beat gemma4 9B at classification.** F1 80.8% vs 63.4%; FPR 33.1% vs 78.9%. Gemma 4 9B has a strong calibration bias toward "low" risk on any message mentioning money or urgency, which the 300-sample UCI ham distribution exposed severely.
2. **RAG hurt on the broader test set.** It helped slightly on the original 70 samples (FPR 28% → 24%) but on 300 samples both models regressed (gemma3 F1 dropped 10pt; gemma4 also worsened). Retrieved FTC cases act as noise on plain conversational ham messages, biasing the model toward false positives. This is why RAG is wired but off by default in production.
3. **All configs maintained near-perfect recall (97–100%)** at this stage. The bottleneck was false positives, not false negatives — exactly the failure mode the SAFE-by-default rule (v3 prompt) was designed to address, but Gemma 4 9B did not respond to it.

**Evolution: 70 → 300 samples**

The original 70-sample evaluation made every model look better. Expanding to 300 with diverse UCI ham exposed the real-world calibration issue:

| Model + prompt + RAG | 70-sample F1 / FPR | 300-sample F1 / FPR | FPR change |
|---|---|---|---|
| gemma3:4b / v2 / no RAG | 92.8% / 28.0% | 80.8% / 33.1% (v3) | +5.1 pt |
| gemma3:4b / v2 / + RAG | **91.5% / 24.0%** | 70.8% / 58.9% (v3) | +34.9 pt |
| gemma4 9B / v3 / no RAG | 83.3% / 72.0% | 63.4% / 78.9% | +6.9 pt |

The interim story was an **inversion** — small model wins on calibration, large model wins on explanation depth — which justified a stopgap hybrid cascade (Gemma 3 triage → Gemma 4 reasoning on non-safe inputs). **The QLoRA experiment above collapsed that trade-off into a single model**, which is why production is no longer a cascade.

See [docs/eval_results.md](docs/eval_results.md) and [docs/prompt_versions.md](docs/prompt_versions.md) for the full methodology and prompt-version history.

---

## Stack

- **Backend**: FastAPI + Ollama HTTP API + ChromaDB (optional, RAG off by default)
- **Frontend**: Next.js 16 + React 19 + TailwindCSS 4
- **Reasoning model**: Fine-tuned Gemma 4 E2B + QLoRA, merged into the base and quantized to Q4_K_M GGUF (3.2 GB), served locally via Ollama as the model `gemma4-scam` (also published as `alicek0914/gemma4-scam` on Ollama Hub)
- **STT**: Whisper-base via HuggingFace ASR pipeline (CUDA, ~150 MB)
- **Training stack**: Unsloth + TRL (SFTTrainer for the SFT pass, DPOTrainer for Loop B)
- **Embedding model**: ChromaDB default (all-MiniLM-L6-v2 equivalent)

---

## Quickstart — run the full demo locally

The fine-tuned model is published on Ollama Hub, so you do **not** have to re-train or convert anything. Five commands from a clean clone get you to a working demo.

### Hardware

| Component | Spec used in development | Minimum to run the demo |
|---|---|---|
| **GPU** | NVIDIA RTX 4060 Ti, 8 GB VRAM | 8 GB VRAM NVIDIA (consumer card OK). CPU-only Ollama works but Gemma 4 inference falls to ~30–60 s per request. |
| **RAM** | 32 GB | 16 GB recommended (Whisper + Ollama + Node dev server) |
| **Disk** | — | ~5 GB free (3.2 GB model + dependencies) |
| **OS** | Windows 11 (host) + WSL2 Ubuntu (training only) | Windows / macOS / Linux all work for the demo runtime. Training/merging requires Linux. |

### Software prerequisites

| Tool | Why | Install |
|---|---|---|
| **Ollama** | serves the fine-tuned `alicek0914/gemma4-scam` model | https://ollama.com/download |
| **Python ≥ 3.11** | FastAPI backend + Whisper STT | https://www.python.org/downloads/ |
| **Node.js ≥ 20** | Next.js frontend | https://nodejs.org |
| **Tesseract** *(optional, for image OCR demo)* | `pytesseract` Python wrapper drives this binary | Win: https://github.com/UB-Mannheim/tesseract/wiki · macOS: `brew install tesseract` · Linux: `apt install tesseract-ocr` |

### Five-command quickstart

```bash
# 1. Pull the fine-tuned model (3.2 GB Q4_K_M GGUF, hosted on Ollama Hub)
ollama pull alicek0914/gemma4-scam

# 2. Clone the repo
git clone https://github.com/Alice0914/gemma4_scam-sentinel.git
cd gemma4_scam-sentinel

# 3. Backend deps + start FastAPI on :8000
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 4. (new terminal) Frontend deps + start Next.js on :3000
cd frontend && npm install && npm run dev

# 5. Open http://localhost:3000/demo
```

The repo references the model as `gemma4-scam`. If you pulled it under the namespaced name, alias it locally:

```bash
ollama cp alicek0914/gemma4-scam gemma4-scam
```

That's it — `/demo` route loads the iPhone emulator with the five built-in scenarios (live audio call, BEC wire, Chase phish, image smishing MMS, normal family message). The model + Whisper-base STT run entirely on your local GPU; no cloud calls at runtime.

### Optional: RAG index

RAG is **off by default** (the 300-sample eval showed it hurt on conversational ham — see Findings). Two switches control it:

1. **Build the index** (one-time): `python backend/rag.py` → writes ChromaDB files to `data/vector_store/`.
2. **Enable retrieval at runtime**: set `SCAM_SENTINEL_RAG=1` before starting uvicorn.

```bash
# Windows PowerShell
$env:SCAM_SENTINEL_RAG = "1"
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# macOS / Linux
SCAM_SENTINEL_RAG=1 uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

`GET /health` reports `"rag": "enabled"` or `"rag": "disabled (default)"` so you can verify. Programmatic callers can also pass `agent.analyze(signals, use_rag=True)` directly; the env var is just the demo-friendly toggle.

### Troubleshooting

- **`HTTP 500` on `/analyze/text`** → `ollama list` must show `gemma4-scam` (or `alicek0914/gemma4-scam`). Pull it first.
- **`Tesseract binary not found`** → only affects the *Upload image (OCR)* tab. The other five demo scenarios still work.
- **Whisper falls back to CPU** → ensure `torch` was installed with the CUDA wheel for your driver (`pip install torch --index-url https://download.pytorch.org/whl/cu124` for CUDA 12.4).
- **Port 3000 / 8000 already in use** → set `--port` on the backend and update `BACKEND` in `frontend/app/demo/page.tsx` to match.

---

## Deploying the fine-tuned model (QLoRA → Ollama)

End-to-end path used to put `Alice0914/gemma4-e2b-scam-sentinel` into Ollama as `gemma4-scam`. Steps 2–4 run inside **WSL2 Ubuntu**; the LoRA→GGUF toolchain is Linux-first.

### 1. Train the QLoRA adapter (Colab L4)

```python
# Colab Pro, ~50 min on L4
from unsloth import FastLanguageModel
from trl import SFTTrainer, SFTConfig

model, tokenizer = FastLanguageModel.from_pretrained(
    "unsloth/gemma-4-E2B-it-unsloth-bnb-4bit",
    max_seq_length=2048,
    load_in_4bit=True,
)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj"],
)
# train on data/synthetic/train.jsonl (3,100 samples), 2 epochs
trainer = SFTTrainer(model=model, tokenizer=tokenizer, ...)
trainer.train()
model.push_to_hub("Alice0914/gemma4-e2b-scam-sentinel")  # ~110 MB LoRA
```

### 2. Merge LoRA into the base (WSL2)

The 4-bit base has to be re-loaded in 16-bit for the merge to be numerically valid — you cannot merge into a quantized base.

```bash
pip install -U "unsloth @ git+https://github.com/unslothai/unsloth.git" \
              "transformers>=5.5.1" peft

python scripts/merge_lora.py \
    --adapter Alice0914/gemma4-e2b-scam-sentinel \
    --output  /home/alice/scam-models/gemma4-scam-merged
# → 9.6 GB safetensors
```

### 3. Convert HF → GGUF (WSL2)

```bash
git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp
cd ~/llama.cpp && pip install -r requirements.txt cmake
cmake -B build && cmake --build build --config Release -j

python convert_hf_to_gguf.py \
    /home/alice/scam-models/gemma4-scam-merged \
    --outfile /home/alice/scam-models/gemma4-scam-f16.gguf \
    --outtype bf16
# → 9.3 GB f16 GGUF
```

### 4. Quantize to Q4_K_M (WSL2)

```bash
~/llama.cpp/build/bin/llama-quantize \
    /home/alice/scam-models/gemma4-scam-f16.gguf \
    /home/alice/scam-models/gemma4-scam-q4.gguf \
    Q4_K_M
# → 3.2 GB, fits fully on 8 GB GPU
```

### 5. Register with Ollama (host OS where the backend runs)

Copy `gemma4-scam-q4.gguf` to the host machine (in this project: `models/gemma4-scam-q4.gguf`), then:

```bash
# models/Modelfile
FROM ./gemma4-scam-q4.gguf
PARAMETER temperature 0.3
PARAMETER num_ctx 4096
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.2
```

```bash
cd models
ollama create gemma4-scam -f Modelfile
ollama list                       # should show gemma4-scam:latest 3.4 GB
ollama run  gemma4-scam "hi"      # smoke test
```

The backend (`backend/reasoning_agent.py` → `DEEP_MODEL = "gemma4-scam"`) talks to it over `http://localhost:11434`.

---

## Why Gemma 4

- **Native function calling** drives the 12 protective tools — turning detection into action.
- **Multimodal context** lets one model reason over transcript + metadata + (optional) retrieved cases simultaneously.
- **Open weights** enable on-device deployment via llama.cpp / Ollama — the demo runs entirely on a local RTX 4060 Ti 8 GB, no cloud inference at runtime (Special Tech Track eligibility).
- **QLoRA-friendly architecture** — the E2B variant (~5B params) fits LoRA fine-tuning on a single L4 in under an hour, and the merged Q4_K_M GGUF fits on consumer 8 GB GPUs.
- **Long context** lets the full system prompt + retrieved cases (when RAG is on) coexist in a single inference pass.

---

## Repo layout

```
scam-sentinel/
├── CLAUDE.md                       # Source of truth for design decisions
├── README.md                       # this file
├── finetune_gemma4_e2b.ipynb       # Colab notebook used for the SFT QLoRA run
├── backend/                        # FastAPI + reasoning agent + 12 tools
│   ├── main.py                    # endpoints: /health, /analyze/{text,image,voice,voice_chunk,voice_full}, /feedback
│   ├── reasoning_agent.py         # Ollama client + user_message cleaner + tool inference
│   ├── finetuned_agent.py         # optional in-process PEFT path (fallback to Ollama if unavailable)
│   ├── stt.py                     # Whisper-base wrapper (HF pipeline, long-form chunking)
│   ├── tools.py
│   ├── rag.py                     # ChromaDB retriever (opt-in)
│   └── prompts/system_prompt.md   # v3 (SAFE-by-default rule)
├── frontend/
│   ├── public/sample_mms/         # demo MMS image assets (fedex_scam.png, etc.)
│   └── app/
│       ├── page.tsx               # baseline single-scenario demo
│       ├── demo/page.tsx          # main phone-emulator demo (5 scenarios + live call)
│       └── components/            # PhoneEmulator / AnalysisPanel (used by baseline)
├── data/
│   ├── synthetic/                 # train.jsonl (3,100), dev.jsonl (771)
│   ├── evaluation/                # eval_set.jsonl (300), eval_set_70.jsonl (backup)
│   ├── rag_cases.jsonl            # 117 FTC/APWG real cases for RAG
│   ├── vector_store/              # ChromaDB persistent index
│   ├── user_feedback.jsonl        # 👍/👎 stream from /feedback
│   └── dpo_pairs.jsonl            # built from user_feedback via scripts/build_dpo_pairs.py
├── models/
│   ├── Modelfile                  # Ollama spec: FROM ./gemma4-scam-q4.gguf + params
│   └── gemma4-scam-q4.gguf        # 3.2 GB merged QLoRA → Q4_K_M (gitignored)
├── scripts/
│   ├── generate_synthetic.py
│   ├── extract_real_seeds.py
│   ├── filter_quality.py
│   ├── prepare_finetune_data.py
│   ├── expand_eval_set.py         # 70 → 300 sample expansion
│   ├── evaluate.py
│   ├── train_lora.py              # SFT QLoRA (Colab L4 path)
│   ├── merge_lora.py              # LoRA → merged bf16 safetensors (WSL2)
│   ├── build_dpo_pairs.py         # feedback → preference pairs (Loop B step 1)
│   ├── train_dpo.py               # DPO from SFT adapter (Loop B step 2)
│   ├── self_critique.py           # Constitutional self-critique (Loop A)
│   ├── seed_demo_feedback.py      # backfill borderline-normal feedback for Loop A
│   └── fix_train_labels.py        # audit/repair synthetic training labels
└── docs/
    ├── eval_results.md
    ├── prompt_versions.md
    └── diagrams/
        ├── 01_system_overview.mmd
        ├── 02_cascade_flow.mmd
        ├── 03_self_improving_cascade.mmd
        ├── Scam_Sentinel_System_Overview.png   # rendered, embedded in README
        └── Self_improving_Cascade.png          # rendered, embedded in README
```

---

## Next steps

The baseline that was originally listed here ("split SFT to Colab, serve locally") shipped — it is now the production runtime documented in [§Deploying the fine-tuned model](#deploying-the-fine-tuned-model-qlora--ollama). Remaining work, post-submission:

1. **Close the DPO loop on real volume** — current `data/user_feedback.jsonl` has only a handful of records. Once the demo collects ≥200 thumbs-down events from real users, run `scripts/build_dpo_pairs.py` + `scripts/train_dpo.py` and A/B vs the locked SFT adapter on `data/evaluation/eval_set.jsonl`.
2. **Recover recall lost to precision-first calibration** — fine-tuning dropped recall 96.8% → 76.8%. The Self-Improving Cascade (Loop A: prompt rewrites from false alarms; Loop B: DPO from confirmed misses) is the recovery mechanism — see [docs/diagrams/03_self_improving_cascade.mmd](docs/diagrams/03_self_improving_cascade.mmd).
3. **Mobile-native deployment** — the Q4_K_M GGUF (3.2 GB) is small enough for LiteRT / MediaPipe LLM Inference API on flagship Android (8 GB+ RAM). The current demo is web-only on a desktop with discrete GPU; on-device mobile inference is the next privacy boundary.
4. **Re-enable RAG once curated** — the 117-case index hurt on the 300-sample test set because the cases skew toward scam summaries, biasing retrievals when the query is benign. A category-balanced index (50% scam / 50% benign exemplars) is needed before RAG comes back online by default.
5. **Stylometric baseline per saved contact (SIM-swap / hijacked-account detection)** — for messages from a saved contact, build a per-contact writing-style fingerprint from message history (n-gram distributions, sentence-length distribution, emoji usage, time-of-day patterns, sentence embeddings) and flag the message when it deviates from baseline beyond a tuned threshold. Today the demo opens saved-contact messages without auto-scanning and exposes a manual "Scan with Sentinel" button as the user-triggered fallback; the stylometric layer would turn that into an automatic second opinion when behavior drifts, catching SIM-swap and account-hijack scams the current text-only classifier alone cannot.

---

## Project north star

Every architectural choice — QLoRA fine-tuning over prompt-only baselines once the data justified it, function calling over passive warning, plain language over probability scores, on-device inference over cloud APIs — serves to prove one sentence:

> **"This is not a final forensic deepfake detector. It is a multimodal scam risk assistant that combines phone call transcript analysis, conversation patterns, and verification workflows."**
