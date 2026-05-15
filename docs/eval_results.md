# Scam Sentinel — Evaluation Results

**Evaluation script**: `python scripts/evaluate.py --model <model> [--rag] --output results/<file>.json`

---

## Final 300-sample results (2026-05-06)

**Test set**: 300 hand-labeled / training-disjoint real samples
- 70 hand-labeled (30 FTC scam + 30 normal + 10 edge cases) — original evaluation set
- 230 UCI SMS Spam Collection (150 ham + 80 spam, all excluded from training via the `seeds_real.jsonl` filter)

| Setup | Accuracy | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| **gemma3:4b / v3 / no RAG** | **80.3%** | 68.1% | 99.2% | **80.8%** | **33.1%** |
| gemma3:4b / v3 / + RAG | 65.7% | 54.8% | 100.0% | 70.8% | 58.9% |
| gemma4 9B / v3 / no RAG | 53.0% | 46.9% | 97.6% | 63.4% | 78.9% |

### Final findings

1. **gemma3:4b decisively beats gemma4 9B at classification on a balanced real-data test.** F1 80.8% vs 63.4%; FPR 33.1% vs 78.9%. Gemma 4 9B's "low risk on anything mentioning money" calibration bias was masked by the smaller 70-sample set and is severe on 300 samples.
2. **RAG hurts on the broader test set.** Retrieved FTC cases act as noise on plain conversational ham messages from UCI, biasing the model toward false positives. The RAG index needs category-balanced curation (currently FTC-only, mostly real scams) before it can help on diverse ham distributions.
3. **All configs maintain near-perfect recall (97–100%).** The bottleneck is false positives, not missed scams.
4. **Production model**: gemma3:4b without RAG. gemma4 9B is reserved for explanation richness on demo paths where latency is acceptable.

---

## Original 70-sample results (2026-05-03, archive)

**Evaluation set**: 70 hand-labeled real samples (30 scam FTC cases + 30 normal + 10 edge cases)

---

## Results Table

| Model | Prompt | RAG | Accuracy | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|---|---|
| gemma4 9B | v1 (baseline) | No | 62.9% | 65.1% | 91.1% | 75.9% | 88.0% |
| gemma4 9B | v2 (improved) | No | 71.4% | 69.2% | 100.0% | 81.8% | 80.0% |
| gemma4 9B | v3 (SAFE rule) | No | 74.3% | 71.4% | 100.0% | 83.3% | **72.0%** |
| gemma4 9B | v1 | Yes | 64.3% | 65.6% | 93.3% | 77.1% | 88.0% |
| gemma3:4b | v2 | No | 90.0% | 86.5% | 100.0% | 92.8% | 28.0% |
| **gemma3:4b** | **v2** | **Yes** | **88.6%** | **87.8%** | **95.6%** | **91.5%** | **24.0%** |

*FPR = False Positive Rate (flagging a safe message as suspicious). Lower is better for user trust.*

---

## Key Findings

### 1. Prompt engineering is the highest-ROI improvement for gemma4
- Baseline → v2: **+5.9% F1, -8% FPR** (no training required, ~2 hours of work)
- This validates the Section 12 decision to skip fine-tuning in favor of prompt engineering

### 2. RAG improves gemma3:4b but not gemma4
- gemma3:4b + RAG: **FPR drops from 28% to 24%** and F1 stays above 91%
- gemma4 + RAG: FPR stays at 88% (model has deeper calibration issue)
- RAG context provides real FTC case citations in output — high demo value regardless

### 3. gemma3:4b significantly outperforms gemma4 at classification
- gemma3:4b FPR: **28%** vs gemma4: **80–88%**
- gemma3:4b F1: **91.5–92.8%** vs gemma4 v2: **81.8%**
- **However**: gemma4's value is in **explanation quality, tool calling, and long-context reasoning**
  - Richer user_message with specific FTC case citations
  - Better chain-of-thought reasoning visible to users
  - Higher recall (less likely to miss critical scams)

### 4. Binary threshold matters
- Current evaluation: any prediction of `low/medium/high/critical` = positive (scam flag)
- `low` risk is a subtle informational note in the UI, not a hard alarm
- If threshold moved to `medium+` for hard alarm: FPR for gemma4 v2 drops significantly

---

## Error Analysis

### Safe messages most commonly misflagged by gemma4:
- Small money requests from family (`$40 for groceries`) → predicted: low
- Appointment reminders with "urgent" language → predicted: low
- Airline/ride-share notifications → predicted: low or critical (RAG confused model)
- `chase.com` bank statement → predicted: critical (RAG pulled bank phishing cases)

### Root cause:
gemma4 9B has a strong internal prior toward `low` for any message involving money or urgency, even with explicit safe-examples in the prompt. This is a model calibration issue that fine-tuning would address but prompt engineering only partially corrects.

---

## How to reproduce

```bash
# Build RAG index first (one-time)
python backend/rag.py

# Run individual evaluations
python scripts/evaluate.py --model gemma4 --output results/track_a_v2.json
python scripts/evaluate.py --model gemma4 --rag --output results/track_a_rag.json
python scripts/evaluate.py --model gemma3:4b --output results/track_light.json
python scripts/evaluate.py --model gemma3:4b --rag --output results/track_light_rag.json

# Compare
python scripts/evaluate.py --compare results/track_a_v2.json results/track_light.json results/track_light_rag.json
```
