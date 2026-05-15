# Scam Sentinel — Multimodal Scam Risk Assistant

> **Core positioning (do not deviate from this):**
> "This is not a final forensic deepfake detector. It is a multimodal scam risk assistant that combines phone call transcript analysis, conversation patterns, and verification workflows."

This document is the source of truth for Claude Code when working on this project. Read it fully before suggesting code or making decisions.

---

## 1. Project context

### What this is
A hackathon MVP for the **Gemma 4 Good Hackathon** (deadline: May 18, 2026). The project competes in:
- **Main Track** ($100K pool)
- **Safety & Trust Impact Track** ($10K)
- Potentially **Special Tech Track** if on-device deployment works (Ollama / LiteRT / Cactus, $10K each)

### What problem we solve
Modern scams are not just "is this voice fake?" — they combine fake voice calls, urgent texts, account requests, authority impersonation, video deepfakes, phishing emails, and emotional pressure. Users need to know:
1. Is this whole situation a scam?
2. Why is it dangerous?
3. What should I do right now?
4. How do I verify with my family?

### Who we serve
General public (not just the elderly). Demo scenarios target multiple demographics: a grandparent receiving a fake-grandson voice call, a 30-something employee receiving a BEC wire request, a 20-something receiving a romance scam. UI should be modern and clean by default with an optional accessibility mode (large text, simplified layout) for older users.

### Why we will win
1. **Reframing**: Most teams will build deepfake detectors. We frame the problem as situation safety, not media authenticity.
2. **Function Calling as differentiator**: Gemma 4's native function calling lets us go beyond "warning displayed" to "actions taken automatically" (notify family, generate secret question, block payment, etc.). This is the technical depth we showcase.
3. **Plain language reasoning**: Output is not a probability score; it's the four-question answer in language a 70-year-old or a 20-year-old can both act on in 5 seconds.

### Hackathon evaluation criteria (always optimize for these)
- **Impact & Vision (40 points)**: Real-world problem, inspiring vision, tangible positive change
- **Video Pitch & Storytelling (30 points)**: 3-minute YouTube video, exciting and engaging
- **Technical Depth & Execution (30 points)**: Innovative use of Gemma 4 features, working code

---

## 2. Architecture

### High-level data flow
```
Input (voice clip / text message / email + metadata)
        ↓
Signal Extractors (parallel)
  - Voice authenticity (mel spectrogram, prosody anomalies, synthetic likelihood)
  - Speech-to-text (transcript, tone, urgency cues)
  - Metadata features (caller ID, time, links, sender info)
        ↓
Gemma 4 Scam Reasoning Agent (the core)
  - Combines all signals
  - Detects: impersonation, urgency, secrecy, payment pressure, suspicious links, OTP requests, phone avoidance
  - Outputs: risk_level, plain language reasons, tool_calls
        ↓
Function Calling Tool Registry (12 tools = 6 core + 6 channel-specific)
  Core verification & response:
  - notify_trusted_contact
  - suggest_callback
  - generate_secret_question
  - start_wait_timer
  - create_incident_report
  - block_payment_intent
  Channel-specific defenses:
  - block_phone_number
  - block_email_sender
  - check_url_safety
  - verify_image_message
  - show_official_contact
  - flag_red_phrases
        ↓
User-facing output (warning UI + action buttons + family alert)
```

### The three core features (MVP scope)

#### Feature 1: Suspicious Call & Voice Risk Detection
- **MVP scope**: voice clip upload or pre-recorded demo audio analysis. No real-time call interception in MVP.
- **Output style**: NOT "synthetic voice 95%" alone. Always paired with plain language reasons and recommended actions.
- **Example output**:
  ```
  Risk Level: High
  
  Why this may be suspicious:
  1. The caller creates urgency: "Send money right now."
  2. The caller asks for secrecy: "Don't tell anyone."
  3. The caller avoids identity verification.
  4. The voice has possible synthetic speech patterns.
  
  Recommended action:
  - Call your grandson directly using the saved contact.
  - Do not send money during this call.
  - Notify your trusted family contact.
  ```

#### Feature 2: Message / Email Scam Pattern Detection
User pastes SMS, kakao-style message, or email. The agent detects and explains these patterns:
- Urgency manipulation
- Family/identity impersonation
- Phone-call avoidance
- New bank account requests
- Secrecy demands
- Suspicious link click pressure
- OTP / password requests

This is where Gemma's LLM strength shines: contextual, intent-based, social engineering pattern recognition with natural language explanation.

#### Feature 3: Family Verification Workflow
Connects detection to safe action. NOT just "warning displayed" — concrete next steps:
- Notify registered family member
- Suggest calling the saved family number directly
- Generate a verification question only the real family member would know
- 2-minute wait timer before any money transfer
- "Don't send money until verification complete" hard gate

This feature is the strongest differentiator and should be prominently featured in the demo video.

### Why Gemma 4 specifically
Gemma 4 is used as a **risk situation interpretation + explanation + action recommendation engine**, not a simple classifier. We leverage:
- **Native function calling**: For the 12 verification & defense action tools
- **Multimodal understanding**: Audio spectrograms + text + metadata in one prompt
- **Open weights**: Allows on-device deployment for privacy (Special Tech Track eligibility)
- **Long context**: Multi-turn conversation analysis

### Single-model runtime (current production, post-QLoRA)
Every request goes directly to the fine-tuned `gemma4-scam` model (Gemma 4 E2B + QLoRA merged into the base and quantized to Q4_K_M GGUF, served via Ollama). The cascade described below is **retained in code as a fallback path** but is **off by default** (`use_cascade=False`).

**Historical context — the Hybrid cascade (Gemma 3 + Gemma 4)** was production before the QLoRA adapter shipped. It used:

1. **Stage 1 — Gemma 3 4B fast classifier**: returned `risk_level` only. The 300-sample eval showed gemma3:4b was the stronger pure classifier (F1 80.8%). Ran with a compact `backend/prompts/fast_classifier.md` prompt at ~64 max_tokens.
2. **Stage 2 — Gemma 4 8B deep reasoner**: only invoked when Stage 1 returned non-`safe`. Produced plain-language reasoning, the four-question `user_message`, and the function-calling `tool_calls`.

The QLoRA model (F1 86.1% / FPR 1.1%) cleared both axes on its own, so production collapsed to a single fine-tuned model. The cascade code path remains in `reasoning_agent.py` for parity-eval runs and as a safety net.

---

## 3. Function Calling specification

The reasoning agent has access to **12 tools**, organized into two groups: 6 core verification/response tools and 6 channel-specific defense tools. Their definitions must be strictly maintained.

### Group A — Verification & response (6 core)

```python
SCAM_SENTINEL_TOOLS = [
    {
        "name": "notify_trusted_contact",
        "description": "Send a push notification to a registered family member when scam risk is high. Use when risk_level is 'high' or 'critical'.",
        "parameters": {
            "contact_id": "string, the trusted contact to notify",
            "risk_summary": "string, one sentence summary",
            "incident_type": "enum: voice_scam, text_scam, email_scam"
        }
    },
    {
        "name": "suggest_callback",
        "description": "Recommend the user call back the real saved contact number, not the incoming number. Use when impersonation is suspected.",
        "parameters": {
            "claimed_identity": "string, who the caller claimed to be",
            "saved_contact_number": "string, the verified number"
        }
    },
    {
        "name": "generate_secret_question",
        "description": "Create a verification question only the real family member would know. Use when the caller claims to be a family member.",
        "parameters": {
            "claimed_relationship": "string, e.g. son, daughter, grandson",
            "context_hints": "array, e.g. shared memories, pet names"
        }
    },
    {
        "name": "start_wait_timer",
        "description": "Activate a 2-minute cool-down before any money transfer. Use when scammer creates urgency around payment.",
        "parameters": {
            "duration_seconds": "integer, default 120",
            "reason": "string, why the timer is needed"
        }
    },
    {
        "name": "create_incident_report",
        "description": "Save the analyzed conversation to incident history for later review. Always call when risk_level is medium or higher.",
        "parameters": {
            "channel": "enum: voice, sms, email",
            "patterns_detected": "array of pattern tags",
            "raw_content": "string, the original message or transcript"
        }
    },
    {
        "name": "block_payment_intent",
        "description": "Show a hard confirmation gate before any money transfer link is opened. Use when payment pressure is detected.",
        "parameters": {
            "trigger_keywords": "array, e.g. send money, transfer now"
        }
    }
]
```

### Group B — Channel-specific defenses (6 extended)

```python
SCAM_SENTINEL_TOOLS_EXTENDED = [
    {
        "name": "block_phone_number",
        "description": "Add the caller's phone number to the device blocklist and file a fraud report. Use for voice or SMS scams at risk_level medium or higher.",
        "parameters": {
            "phone_number": "string",
            "reason": "string, one-sentence reason",
            "incident_type": "enum: voice_scam, sms_scam"
        }
    },
    {
        "name": "block_email_sender",
        "description": "Add the sender (and optionally their domain) to the spam filter. Use for email scams at risk_level medium or higher.",
        "parameters": {
            "email_address": "string",
            "sender_domain": "string|null",
            "reason": "string"
        }
    },
    {
        "name": "check_url_safety",
        "description": "Evaluate a URL for phishing / lookalike-domain heuristics and prepare a blocking popup. Use whenever a link appears OR phishing_link is detected.",
        "parameters": {
            "url": "string",
            "detected_in": "enum: sms, email, voice_transcript"
        }
    },
    {
        "name": "verify_image_message",
        "description": "Re-analyze image-extracted text (OCR from MMS or screenshot attachments). Use when metadata.image_extracted_text is present.",
        "parameters": {
            "extracted_text": "string",
            "image_source": "string"
        }
    },
    {
        "name": "show_official_contact",
        "description": "Surface the verified real contact information for an impersonated brand (Chase, USPS, IRS, Amazon, etc.). Use whenever a known brand is impersonated.",
        "parameters": {
            "impersonated_brand": "string"
        }
    },
    {
        "name": "flag_red_phrases",
        "description": "Highlight specific dangerous phrases inside the original message in the UI. Use whenever risk_level is medium or higher.",
        "parameters": {
            "phrases": "array of strings, exact phrases quoted from the message",
            "risk_categories": "array of strings parallel to phrases"
        }
    }
]
```

Do not add new tools beyond these 12 without explicit instruction. If a feature seems to need a 13th tool, first ask whether the existing 12 can be composed instead.

---

## 4. Data strategy

### English only
The MVP uses English data only. Do not generate Korean or other languages without explicit instruction. Demo video may include translated subtitles, but the model itself is English-only for the MVP.

### Real datasets
- **UCI SMS Spam Collection**: ~5,574 labeled English SMS (Kaggle)
- **Enron + APWG**: Phishing emails, ~10K labeled
- **FTC Sentinel**: Public scam case summaries scraped from FTC consumer site
- **ASVspoof 2019 LA**: Voice authenticity, ~7GB. Subset only — do not download ASVspoof 5 full (100GB+).

### Synthetic data (Gemma-generated)
- **8 categories**: family_impersonation, prosecutor_scam, bec_scam, romance_scam, package_scam, bank_phishing, phishing_link, normal
- **10 hand-written seed examples per category** — these determine quality, do not delegate seed writing to AI
- **50 variants per seed** — generated by Gemma 4
- **Total**: ~4,000 samples → after dedup ~3,000

### Quality filtering rules
- Drop near-duplicates using sentence-transformers cosine similarity > 0.9
- Drop samples containing meta-words like "scam", "fake", "synthetic" (real scammers don't use these)
- Drop unrealistic amounts (over $1M, etc.)
- Mask PII in any real data: phone numbers, account numbers, SSN, names with regex

### Evaluation set (CRITICAL)
- Never evaluate on synthetic data alone
- Current set: **300 hand-labeled samples** in `data/evaluation/eval_set.jsonl`
  - 175 safe (normal) + 7 low + 79 medium + 26 high + 13 critical
  - Categories: 179 normal, 88 phishing_link, 8 family_impersonation, 6 prosecutor_scam, 5 bec_scam, 5 romance_scam, 5 bank_phishing, 4 package_scam
  - Sources: real FTC cases + normal control + edge cases, expanded from the original 70-sample set (still archived as `eval_set_70.jsonl`)
- Plus 20 voice clips: 10 synthetic + 10 real from ASVspoof
- Train on synthetic, evaluate on real — this is what we report in the writeup

---

## 5. Tech stack decisions

### Backend
- **Language**: Python 3.11+
- **Framework**: FastAPI (async, fast, good for LLM streaming)
- **Model serving**:
  - **Single fine-tuned model via Ollama** (production runtime): `gemma4-scam` — Gemma 4 E2B + QLoRA merged into the base and quantized to Q4_K_M GGUF (~3.2 GB). Served locally over the Ollama HTTP API.
  - **Cascade fallback** (in code, off by default): Gemma 3 4B triage → Gemma 4 8B deep reasoner. Retained for parity-eval runs against the single-model baseline.
  - On-device demo runs entirely local on an 8 GB consumer GPU (Special Tech Track eligibility).
- **Audio processing**: librosa for mel spectrograms, soundfile for I/O
- **STT**: Whisper (local) or Gemma 4 multimodal if it handles audio directly

### Frontend
- **Framework**: Next.js 14 (App Router) + React
- **Styling**: TailwindCSS only — no UI libraries that bloat the bundle
- **Modern aesthetic**: Clean white surfaces, dark mode support, subtle animations
- **Accessibility mode**: Toggle for larger text, simpler layout, single-column

### Infrastructure
- **Live demo**: Vercel for frontend, Hugging Face Spaces or Modal for backend
- **Repo**: GitHub, public, well-documented README

### What we do NOT use
- No real telephony integration in MVP (Twilio, etc.)
- No bank app integration in MVP
- No iOS native app — Android or web only
- **No fine-tuning by default**. Pre-trained Gemma 4 8B + prompt engineering + RAG is the baseline. Fine-tuning is only considered if ALL Day 7 checkpoint conditions clear AND we are ahead of schedule by Day 11. See Section 12 for the full reasoning.
- No video deepfake analysis unless Day 7 checkpoint clears
- No multilingual support beyond English

---

## 6. Working principles

### Day 7 is the make-or-break checkpoint
By end of Day 7, two channels (text + voice) must work end-to-end. If they don't, immediately drop video deepfake, drop fine-tuning, drop on-device deployment, and focus solely on polishing what works. Be honest at this checkpoint.

### Day 13 is feature freeze
After Day 13, no new features. Only bug fixes, video, and writeup. This rule is non-negotiable.

### Video gets 3 full days (Day 14-16)
The video is 30% of the score and is what judges see first. Three full days for shoot + edit + writeup is the minimum.

### "Plain language" is not a layer, it's the product
Every output the user sees should be readable in 5 seconds by a non-technical user. If a feature can only be explained with jargon, redesign the feature, don't translate after.

### False positives kill the product
A normal "Mom, can you send $20 for groceries?" should NOT trigger a high-risk warning. Always include "normal" counter-examples in evaluation. Day 12 buffer day is for false positive tuning specifically.

---

## 7. File structure

```
scam-sentinel/
├── CLAUDE.md (this file - read first)
├── README.md (public-facing project description)
├── data/
│   ├── raw/                  (downloaded datasets, gitignored if large)
│   ├── synthetic/            (Gemma-generated training data)
│   ├── evaluation/           (300 hand-labeled samples)
│   ├── seeds.jsonl           (10 seeds per category, hand-written)
│   ├── seeds_real.jsonl      (571 real UCI spam seeds, classified)
│   ├── rag_cases.jsonl       (117 real FTC/APWG cases for RAG)
│   ├── vector_store/         (ChromaDB index built from rag_cases.jsonl)
│   └── taxonomy.json         (8-category scam taxonomy)
├── models/
│   └── gemma-4-8b-it/        (downloaded weights, gitignored)
├── backend/
│   ├── main.py               (FastAPI app)
│   ├── reasoning_agent.py    (Gemma 4 prompt + function calling)
│   ├── voice_extractor.py    (mel spectrogram, authenticity probes)
│   ├── stt.py                (speech-to-text wrapper)
│   ├── tools.py              (12 function-calling tools)
│   ├── rag.py                (ChromaDB retriever for real scam cases)
│   ├── metadata.py           (rule-based metadata feature extraction)
│   └── prompts/
│       ├── system_prompt.md  (the core reasoning agent prompt)
│       └── synthesis.md      (synthetic data generation prompt)
├── frontend/
│   ├── app/
│   │   ├── page.tsx          (main demo UI)
│   │   ├── components/
│   │   └── styles/
│   └── package.json
├── scripts/
│   ├── generate_synthetic.py (Day 1-2 data generation)
│   ├── filter_quality.py     (dedup, regex filter)
│   ├── evaluate.py           (run on evaluation set, output metrics)
│   └── download_data.sh      (one-shot dataset download)
└── docs/
    ├── architecture.md       (technical writeup for hackathon submission)
    ├── video-script.md       (3-minute video script)
    └── eval_results.md       (precision, recall, false positive rate)
```

---

## 8. The 16-day plan summary

| Day | Phase | Goal |
|---|---|---|
| 1 | Foundation | Setup, data download, taxonomy, seeds, synthesis script |
| 2 | Foundation | Generate 4000 synthetic samples, filter, build evaluation set |
| 3 | Foundation | First end-to-end demo (text input → analysis → action) |
| 4 | Build | Android or web app shell, paste-text demo polished |
| 5 | Build | Voice clip upload, STT, phone call transcript analysis stub |
| 6 | Build | Voice signals fed into reasoning agent, combined verdict |
| 7 | Build | **CHECKPOINT** — 2 channels stable? Drop extras if not |
| 8 | Build | Optional video frame analysis OR polish existing |
| 9 | Build | Function calling — all 12 tools actually wired up |
| 10 | Build | Verification workflow UI: callback, secret question, timer |
| 11 | Polish | UI polish, accessibility mode, false positive tuning |
| 12 | Polish | Buffer day — bugs, edge cases, real evaluation set run |
| 13 | Polish | **FEATURE FREEZE** — video script + storyboard |
| 14 | Ship | Video shoot — 3 scenarios (grandma, BEC, romance) |
| 15 | Ship | Video edit + voiceover, writeup full draft, repo cleanup |
| 16 | Ship | YouTube upload, final review, submit by 11:59 PM UTC |

---

## 9. Code style preferences

### Python
- Type hints on every function signature
- `pydantic` models for all structured I/O (request, response, agent output)
- Docstrings on public functions, no need for docstrings on trivial helpers
- Async by default for I/O-bound code (FastAPI endpoints, model inference if streaming)
- No global state — pass model instance through dependency injection

### TypeScript / React
- Server Components by default, Client Components only when needed
- TailwindCSS utility classes inline; no CSS modules unless complex
- No state management library — useState + Context is enough for MVP
- Props are typed interfaces, no `any`

### General
- Clear variable names over clever ones (`is_synthetic_voice` not `isv`)
- Comments explain WHY, not WHAT — the code shows what
- No premature abstraction — duplicate twice before extracting

---

## 10. Things to push back on

When I (the user) ask for something, push back if:

- **Feature creep before Day 7 checkpoint**: "Should we also add real-time call interception?" → No, MVP scope is fixed.
- **Adding tools beyond the 12**: The toolset is fixed at 12 (6 core + 6 channel defenses). Always check if existing tools can be composed first.
- **Korean or multilingual support**: English only for MVP. Subtitles in video are fine.
- **Real banking integration**: Out of scope, security risk, no time.
- **Perfect deepfake accuracy**: We are NOT a forensic detector. 75% accuracy + great explanation > 95% accuracy + bare score.
- **Output without plain-language reasoning**: Every output must answer the four user questions.
- **Skipping the evaluation set**: Always evaluate on real data, never report metrics on synthetic-only.

When in doubt, ask: "Does this serve the four user questions, the three core features, and the hackathon evaluation criteria?" If not all three are clear yes, push back.

---

## 11. The core message — keep it visible

This sentence should appear in:
- README.md first paragraph
- Video first 30 seconds
- Writeup opening
- Live demo landing page
- This document (top)

> **"This is not a final forensic deepfake detector. It is a multimodal scam risk assistant that combines phone call transcript analysis, conversation patterns, and verification workflows."**

Everything we build serves to prove this sentence true.

---

## 12. The fine-tuning decision (read before suggesting fine-tuning)

**Default position: we do NOT fine-tune Gemma 4 in the MVP.**

This is a deliberate engineering decision, not laziness. Push back if asked to fine-tune unless the conditions in Section 12.3 are all met.

### 12.1 Why pre-trained Gemma 4 is enough

The core task of this project is reasoning, not classification:
- Identify scam patterns in context
- Explain in plain language why something is suspicious
- Decide which of 12 tools to call
- Suggest verification steps a human can act on

These are tasks Gemma 4 8B already does well out of the box. Pre-trained baseline accuracy on the evaluation set is expected to be 80-85%. Fine-tuning typically adds only 3-5 percentage points for reasoning + explanation tasks (unlike pure classification, where gains are larger).

### 12.2 Why fine-tuning is risky in a 16-day timeline

- Data formatting for instruction tuning takes 1-2 days (need full reasoning chains, not just labels)
- First training run usually fails — debugging GPU OOM, dtype, tokenization issues consumes 1-2 days
- Hyperparameter tuning + re-training: another 1-2 days
- Risk of catastrophic forgetting: model becomes a scam classifier but loses general reasoning, flags "Mom, can you send $20 for groceries?" as high risk
- Risk of overfitting to synthetic data: real evaluation accuracy drops below baseline
- Risk of breaking JSON output format: function calling stops working
- Total cost: 5-7 days, with non-zero probability of net negative impact

That time is better spent on: function calling completeness, UI polish, video production, false positive tuning, RAG implementation.

### 12.3 When to reconsider (Day 11 review only)

Fine-tuning is only on the table if ALL of these are true at Day 11 evening:

1. Text + voice channels both work end-to-end
2. All 12 function calling tools are wired and working
3. Baseline (prompt-engineered Gemma 4) accuracy ≥ 85% on evaluation set
4. Video script is written and approved
5. UI is at "demo-ready" polish level
6. There is a specific failure mode that fine-tuning would address better than prompt iteration

If even one of these is false, do not fine-tune.

### 12.4 What we do instead

Three concrete techniques replace fine-tuning. Each has a dedicated specification section below.

- **Prompt engineering** (see Section 13): Detailed system prompt with the 7 scam pattern definitions, 5-10 few-shot examples, and a 5-step chain-of-thought structure. Recovers ~80% of fine-tuning's expected gain at zero training cost.
- **RAG over real scam cases** (see Section 14): Index 150-200 real FTC and APWG cases as a vector DB. Retrieve the top 3 similar past cases at inference time and inject into context. Produces high-impact demo outputs like "This resembles a 2024 FTC case where the victim lost $9,200."
- **Self-consistency**: Run inference 3 times at temperature 0.3, majority-vote on risk_level. Improves reliability without training. See Section 13.5.

### 12.5 The Unsloth Special Tech Track temptation

The Unsloth Track is worth $10K. Do not optimize for it at the expense of Main Track ($50K first prize). Expected value calculation strongly favors not fine-tuning:
- Strong MVP without fine-tuning → high probability of Main Track placement
- Failed fine-tuning attempt → MVP becomes weaker, may lose Main Track entirely

Special Tech Track eligibility can come from on-device deployment (Ollama, LiteRT) without fine-tuning, which is much lower risk.

---

## 13. Prompt engineering specification

This section defines exactly how the system prompt should be constructed. Section 12 said "we use prompt engineering instead of fine-tuning" — this section says how.

### 13.1 The three pillars

The reasoning agent's prompt is built on three pillars. All three must be present in the final system prompt:

1. **Pattern definitions**: Explicit definitions of the 7 scam patterns (plus 1 "normal" counter-class)
2. **Few-shot examples**: 5-10 worked examples showing input → reasoning → JSON output
3. **Chain-of-thought structure**: Force the model to reason in a fixed sequence before producing the verdict

Together these recover an estimated 80% of what fine-tuning would give us, at zero training cost.

### 13.2 Pattern definitions (must appear in system prompt)

These 7 patterns are what the model must learn to identify. Include all of them in the system prompt with concrete language. Do not abbreviate — the model needs the full description to reason well.

```
1. URGENCY MANIPULATION
   The sender pressures immediate action. Phrases: "right now", "within the hour",
   "before it's too late", "limited time". Real family rarely demands instant action
   without context.

2. IDENTITY IMPERSONATION
   The sender claims to be someone the user trusts (family member, employer, bank,
   government agency) but uses an unknown number, new email, or unusual channel.
   Real people contact you through their saved channels.

3. PHONE-CALL AVOIDANCE
   The sender refuses or actively discourages a callback. Phrases: "don't call me",
   "my phone is broken", "I can only text right now". Real family will accept a
   callback to a known number.

4. NEW-ACCOUNT REQUEST
   The sender asks the user to send money to a bank account number that the user
   has not used before with this person. Real recurring contacts use stable accounts.

5. SECRECY DEMAND
   The sender asks the user not to tell anyone, especially other family members.
   Phrases: "keep this between us", "don't tell mom", "this is confidential".
   Legitimate requests rarely require secrecy from one's own family.

6. SUSPICIOUS LINK PRESSURE
   The sender pushes the user to click a link, especially shortened URLs, lookalike
   domains (paypa1.com, kakao-pay-verify.xyz), or links to verify identity.
   Banks and government agencies do not request verification via SMS links.

7. CREDENTIAL OR OTP REQUEST
   The sender asks for passwords, one-time codes, social security numbers, or
   account credentials. No legitimate institution asks for these in messages.

CONTROL CLASS: NORMAL
   Messages that may superficially resemble scam patterns but are clearly normal:
   "Mom, I love you", "Hey can you grab milk on the way home", "Meeting moved to 3pm".
   The model must NOT flag these as suspicious.
```

### 13.3 Chain-of-thought structure

The system prompt must instruct the model to reason in this exact sequence before producing the JSON. This is what makes the output reliable and explainable.

```
For every input, reason in this order before producing JSON:

Step 1 — IDENTIFY: Which of the 7 patterns are present? List each one with the
        exact phrase from the input that triggered it. If none, the input is
        likely normal.

Step 2 — ASSESS: Given the patterns identified, what is the risk level?
        - safe:     no patterns
        - low:      1 weak pattern
        - medium:   1 strong pattern OR 2 weak patterns
        - high:     2+ strong patterns OR explicit money/credential request
        - critical: 3+ patterns AND money/credential request

Step 3 — EXPLAIN: For each pattern identified, write one sentence in plain language
        that a 70-year-old or 20-year-old can understand in 5 seconds. No jargon,
        no probability scores, no hedging.

Step 4 — DECIDE TOOLS: Based on risk level and patterns, which of the 12 tools
        should be called? See tool descriptions for triggering conditions.

Step 5 — ANSWER FOUR QUESTIONS: The user_message field must answer:
        - Is this whole situation a scam? (yes/no/maybe)
        - Why is it dangerous? (the explanations)
        - What should I do right now? (immediate action)
        - How do I verify with my family? (callback / secret question)

Only after Step 5 is complete, produce the final JSON.
```

### 13.4 Few-shot example format

Include 5-10 worked examples in the system prompt. Each example must show:
- Input (transcript + voice signals + metadata)
- Brief reasoning (one paragraph showing Steps 1-5)
- Final JSON output

The examples should cover variety:
- 1 critical voice scam (fake grandson)
- 1 high-risk text scam (BEC wire transfer)
- 1 medium phishing link
- 1 low-risk borderline case (urgent but legitimate)
- 2 normal control examples (must output safe + empty tool_calls)

The control examples are the most important — they prevent false positives. Without "normal" examples, the model becomes paranoid.

### 13.5 Self-consistency for reliability

For high-stakes decisions, run inference 3 times at temperature 0.3 and take the majority vote on risk_level. This adds latency but reduces flip-flop on edge cases.

```python
def analyze_with_self_consistency(signals: dict, n_samples: int = 3) -> dict:
    results = [reasoning_agent.analyze(signals, temperature=0.3) for _ in range(n_samples)]
    # Majority vote on risk_level
    from collections import Counter
    risk_levels = [r["risk_level"] for r in results]
    final_risk = Counter(risk_levels).most_common(1)[0][0]
    # Use the result whose risk_level matches the majority
    final = next(r for r in results if r["risk_level"] == final_risk)
    return final
```

Use this only for the final verdict, not for every internal call. Three calls per analysis is the upper bound.

### 13.6 Where the system prompt lives

The full prompt template lives in `backend/prompts/system_prompt.md` and is loaded at agent init time. Do not inline-construct prompts inside Python code — keep them in markdown for editability and version control.

---

## 14. RAG specification

This section defines how Retrieval-Augmented Generation is integrated. RAG makes the agent demonstrably better than a bare LLM and produces high-impact demo outputs like "This message strongly resembles a 2024 FTC case in which..."

### 14.1 What we index

Build a vector index over **real scam cases** (not synthetic). Sources:
- FTC Sentinel public summaries (~100 cases, hand-curated)
- APWG phishing email samples (~50 cases)
- Notable news-reported scam cases (~30 cases)

Total target: 150-200 documents in the index. Do not exceed 500 — at MVP scale, more is not better.

**Actual current count**: 117 cases in `data/rag_cases.jsonl`, indexed into ChromaDB at `data/vector_store/`. Below the target — expand if the writeup needs more breadth, but note the 300-sample eval showed RAG hurt rather than helped, so production currently runs without RAG by default (the index is wired but the retriever is only injected when explicitly enabled).

Each document is structured:
```json
{
  "case_id": "ftc-2024-grandparent-001",
  "title": "Grandparent scam with synthetic voice",
  "category": "family_impersonation",
  "year": 2024,
  "summary": "Fraudster used AI voice cloning to impersonate the victim's grandson, claiming an emergency and requesting wire transfer. Pattern: urgency + impersonation + new account.",
  "patterns": ["urgency", "impersonation", "new_account", "phone_avoidance"],
  "outcome": "Victim lost $9,200 before family verified the call was fake.",
  "source_url": "https://reportfraud.ftc.gov/..."
}
```

### 14.2 Embedding and storage

- **Embedding model**: `sentence-transformers/all-MiniLM-L6-v2` (small, fast, local). Do not use OpenAI embeddings — adds external dependency and cost.
- **Vector store**: ChromaDB (local, file-based, zero infrastructure). Alternative: FAISS if ChromaDB is overkill.
- **What gets embedded**: The `summary` field plus the `patterns` field joined as text. Title and outcome are stored as metadata for retrieval.

```python
from sentence_transformers import SentenceTransformer
import chromadb

embedder = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path="./data/vector_store")
collection = client.get_or_create_collection("scam_cases")

# Indexing
text_to_embed = f"{case['summary']} Patterns: {', '.join(case['patterns'])}"
embedding = embedder.encode(text_to_embed)
collection.add(
    ids=[case["case_id"]],
    embeddings=[embedding.tolist()],
    documents=[text_to_embed],
    metadatas=[{"title": case["title"], "outcome": case["outcome"], "year": case["year"]}]
)
```

### 14.3 Retrieval at inference time

When a new input arrives:
1. Build a query string from the transcript + identified patterns (early in chain-of-thought)
2. Retrieve the top 3 most similar past cases
3. Inject them into the reasoning prompt as a "Similar past cases" block

```python
def retrieve_similar_cases(transcript: str, top_k: int = 3) -> list[dict]:
    query_embedding = embedder.encode(transcript).tolist()
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)
    return [
        {
            "title": meta["title"],
            "summary": doc,
            "outcome": meta["outcome"],
            "year": meta["year"]
        }
        for doc, meta in zip(results["documents"][0], results["metadatas"][0])
    ]
```

### 14.4 Prompt integration

The retrieved cases go into a dedicated section of the user message, not the system prompt. This keeps the system prompt static and cacheable while letting context vary per-call.

```
SIGNALS: { ... voice / transcript / metadata ... }

SIMILAR PAST CASES (for reference, not training):
[Case 1] {title}, {year}
  Summary: {summary}
  Outcome: {outcome}

[Case 2] ...
[Case 3] ...

Use these similar cases to inform your reasoning. If the current input
matches a known pattern from these cases, mention that in user_message.
For example: "This message follows the same pattern as a 2024 FTC case..."
```

### 14.5 Why RAG is high-leverage for the demo

- **Specific citations**: "Resembles a 2024 FTC case where the victim lost $9,200" is far more compelling than "appears suspicious"
- **Updatable without retraining**: New scam patterns emerge constantly. Adding a case to the vector store is one line of code, not a fine-tuning run.
- **Explains the verdict**: Judges ask "why does the model think this is a scam?" — RAG provides receipts.
- **Demonstrates Gemma 4 long-context capability**: Loading 3 cases plus full system prompt uses Gemma 4's context window meaningfully.

### 14.6 Implementation budget

- Curating 150 cases: 6-8 hours (Day 2 afternoon)
- Embedding pipeline: 1-2 hours
- Retrieval integration into agent: 1 hour
- Testing: 1 hour

Total: ~half a working day. This is the highest-ROI thing you can build after the baseline reasoning agent works.

### 14.7 What NOT to do with RAG

- Do NOT index the synthetic training data — that defeats the purpose. RAG must retrieve from real cases the model has not seen.
- Do NOT retrieve more than 5 cases per query. Beyond that, signal-to-noise drops and context bloats.
- Do NOT use RAG as the primary detection mechanism. RAG augments the reasoning agent — the LLM still does the verdict. RAG is reference material, not ground truth.

---

## 15. The core message — keep it visible (final reminder)

This sentence is the north star of the entire project. It must appear, verbatim or near-verbatim, in:
- README.md first paragraph
- Video first 30 seconds (spoken or on-screen text)
- Writeup opening paragraph
- Live demo landing page hero text
- This document (top of file)

> **"This is not a final forensic deepfake detector. It is a multimodal scam risk assistant that combines phone call transcript analysis, conversation patterns, and verification workflows."**

Every architectural choice — pre-trained Gemma 4 over fine-tuning, RAG over training data expansion, function calling over passive warning, plain language over probability scores — serves to prove this sentence true.

If you propose a feature or design decision and cannot trace it back to this sentence, the feature does not belong in the MVP.

---

## 16. Baseline vs Fine-tuning: Two-Track Evaluation Strategy

### Why two tracks?

The baseline-vs-fine-tuning comparison is itself a strong writeup asset. It proves one of two valuable claims with data:

- **If fine-tuning shows minimal gain**: "Prompt engineering alone is sufficient — Gemma 4's instruction-following is powerful enough that LoRA adds only marginal value." This validates the Section 12 architecture decision.
- **If fine-tuning shows meaningful gain**: Unlocks the Unsloth Special Tech Track ($10K) and demonstrates that scam detection benefits from domain adaptation.

Either outcome is a win. The comparison is the contribution.

### Track A: Baseline

- **Model**: Pre-trained Gemma 4 8B-IT, weights unchanged
- **Techniques**: System prompt (Section 13) + RAG (Section 14) + self-consistency (Section 13.5)
- **No training required**

### Track B: Fine-tuned

- **Model**: Gemma 4 8B-IT + QLoRA adapter trained on synthetic data
- **Techniques**: Same system prompt + RAG + self-consistency as Track A
- **The only difference from Track A is the model weights.** Prompt, RAG index, and evaluation set are identical.

### Training data format (chat template, JSONL)

Each training sample must include the full chain-of-thought reasoning in the assistant turn — not just the final JSON. This preserves the model's explanation capability.

```jsonl
{
  "messages": [
    {
      "role": "system",
      "content": "<full contents of backend/prompts/system_prompt.md>"
    },
    {
      "role": "user",
      "content": "TRANSCRIPT: 'Son, I'm in jail, send $5000 now, don't tell mom'\nVOICE_SIGNALS: {\"synthetic_likelihood\": 0.82, \"prosody_anomaly\": true}\nMETADATA: {\"caller_id\": \"unknown\", \"new_number\": true}"
    },
    {
      "role": "assistant",
      "content": "Step 1 - IDENTIFY: urgency('send now'), impersonation(unknown number claiming to be son), secrecy('don't tell mom'), phone_avoidance(no callback offered)\nStep 2 - ASSESS: 3 strong patterns + money request → critical\nStep 3 - EXPLAIN: The caller demands instant money, which real family emergencies rarely require without any prior contact. The caller asks for secrecy from other family members, a hallmark of manipulation. The voice shows signs of synthetic generation.\nStep 4 - DECIDE TOOLS: notify_trusted_contact, suggest_callback, generate_secret_question, start_wait_timer, create_incident_report, block_payment_intent\nStep 5 - ANSWER FOUR QUESTIONS: This is very likely a scam. It is dangerous because...\n\n{\"risk_level\": \"critical\", \"patterns\": [\"urgency\", \"impersonation\", \"secrecy\", \"phone_avoidance\"], \"user_message\": \"...\", \"tool_calls\": [...]}"
    }
  ]
}
```

**Critical rule**: The assistant output must always contain Steps 1-5 reasoning before the JSON block. Training on JSON-only outputs will destroy the model's explanation capability and break the product's core value.

### LoRA fine-tuning setup (Unsloth)

```python
from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    "google/gemma-4-8b-it",  # verify exact HF ID before training
    max_seq_length=4096,
    load_in_4bit=True,
)
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    lora_alpha=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
)
# Train with SFTTrainer on data/synthetic/train.jsonl
```

Save the LoRA adapter separately (`models/gemma-4-lora-adapter/`). At inference time, Track B loads base model + adapter; Track A loads base model only.

### Evaluation protocol (identical for both tracks)

Both tracks are evaluated on the same **300-sample real evaluation set** (Section 4, `data/evaluation/eval_set.jsonl`, never synthetic). Report:

| Metric | Description |
|---|---|
| Precision | Of flagged cases, how many are real scams? |
| Recall | Of real scams, how many did the model catch? |
| False positive rate | Normal messages incorrectly flagged as suspicious |
| F1 | Harmonic mean of precision and recall |
| Tool call accuracy | Did the model call the right tools for the risk level? |

False positive rate is the most important metric for user trust. A model that flags "Mom, can you send $20 for groceries?" as high-risk is unusable regardless of recall.

### Data split rules

- **Train (Track B only)**: `data/synthetic/train.jsonl` — 3,100 samples (80% of filtered synthetic)
- **Dev (Track B only)**: `data/synthetic/dev.jsonl` — 771 samples (20% of filtered synthetic), for early stopping
- **Evaluation (both tracks)**: `data/evaluation/eval_set.jsonl` — 300 real samples, never touched during training

The evaluation set must never appear in any training or dev split. Verify with a hash check before training starts.

### When to run fine-tuning

Per Section 12.3, fine-tuning is only attempted if Day 11 conditions all pass. However, the data preparation (train.jsonl formatting) can be done in parallel with baseline development — it costs only ~2 hours and does not block anything. Prepare the data early; decide whether to train late.

### Reporting the comparison

In the writeup and video, report the comparison as a table:

| | Track A (Baseline) | Track B (Fine-tuned) | Delta |
|---|---|---|---|
| Precision | — | — | — |
| Recall | — | — | — |
| False positive rate | — | — | — |
| F1 | — | — | — |

Narrate the delta, not just the numbers. "Fine-tuning improved recall by 4 points but did not change false positive rate — suggesting that the prompt already handles the normal/scam boundary well" is a finding, not just a result.

---

## 17. Final Dataset Composition

### Training data (3 sources combined)

| Source | Raw count | Method | Output file |
|---|---|---|---|
| 80 hand-written seeds | 80 × 13 variants | Gemma 4 via Ollama | `data/synthetic/raw.jsonl` (~1,040) |
| 571 real UCI spam | as-is | extract_real_seeds.py | `data/seeds_real.jsonl` (571) |
| 571 real UCI spam | 571 × 4 variants | Gemma 4 via Ollama | `data/synthetic/raw_real.jsonl` (~2,284) |
| **Total raw** | **~3,895** | | |
| **After filter/dedup** | **~3,500–3,700** | filter_quality.py | `data/synthetic/train.jsonl` + `dev.jsonl` |

### Train / Dev split (synthetic only)

- **Train**: 80% of filtered synthetic → `data/synthetic/train.jsonl`
- **Dev**: 20% of filtered synthetic → `data/synthetic/dev.jsonl`
- Split is stratified by category so all 8 categories are represented in both sets.

### Evaluation set (separate, never used in training)

- **300 hand-labeled real samples** at `data/evaluation/eval_set.jsonl` (expanded from the original 70-sample set, which is archived at `data/evaluation/eval_set_70.jsonl`).
- Risk-level distribution: 175 safe / 7 low / 79 medium / 26 high / 13 critical.
- Category distribution: 179 normal, 88 phishing_link, 8 family_impersonation, 6 prosecutor_scam, 5 bec_scam, 5 romance_scam, 5 bank_phishing, 4 package_scam.
- Both Track A and Track B are evaluated on this set only.

### Generation scripts

```bash
# Step 1: Generate synthetic from hand-written seeds (~1,040)
python scripts/generate_synthetic.py --seeds data/seeds.jsonl --n-variants 13 --output data/synthetic/raw.jsonl

# Step 2: Extract and classify real UCI spam
python scripts/extract_real_seeds.py --output data/seeds_real.jsonl

# Step 3: Generate synthetic from real spam (~2,284)
python scripts/generate_synthetic.py --seeds data/seeds_real.jsonl --n-variants 4 --output data/synthetic/raw_real.jsonl

# Step 4: Combine, filter, split
cat data/synthetic/raw.jsonl data/seeds_real.jsonl data/synthetic/raw_real.jsonl > data/synthetic/combined.jsonl
python scripts/filter_quality.py --input data/synthetic/combined.jsonl --train data/synthetic/train.jsonl --dev data/synthetic/dev.jsonl
```

### Actual results (verified 2026-05-10)

| File | Count |
|---|---|
| `data/seeds.jsonl` (hand-written seeds) | 80 |
| `data/seeds_real.jsonl` (real UCI spam, classified) | 571 |
| `data/synthetic/raw.jsonl` (seeds synthetic) | 1,112 |
| `data/synthetic/raw_real.jsonl` (real spam synthetic) | 2,224 |
| `data/synthetic/combined.jsonl` (raw total) | 3,907 |
| After meta-word filter / dedup (36 dropped) | 3,871 |
| **`data/synthetic/train.jsonl`** | **3,100** |
| **`data/synthetic/dev.jsonl`** | **771** |
| **`data/evaluation/eval_set.jsonl`** (real, held out) | **300** |
| `data/evaluation/eval_set_70.jsonl` (original snapshot, archived) | 70 |
| `data/rag_cases.jsonl` (real cases for RAG) | 117 |
| **`data/synthetic/dev.jsonl`** | **771** |

Category breakdown (train):
- phishing_link: 2,181 (over-represented because UCI seeds skew heavily toward phishing — apply class weights at fine-tune time)
- family_impersonation: 180
- package_scam: 158
- bec_scam: 125
- romance_scam: 122
- bank_phishing: 115
- prosecutor_scam: 115
- normal: 104
