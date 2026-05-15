# Colab Pro Unsloth Fine-tuning — Step-by-Step Guide

## Step 0 — Subscribe to Colab Pro (5 min)

1. Go to https://colab.research.google.com and confirm the account in the top-right (alicek0914@gmail.com).
2. Open the hamburger menu (top-left) → "Upgrade to Colab Pro".
3. Pick **Colab Pro ($9.99/month)** — not Pay-as-you-go. This gives 100 compute units per month.
4. After payment, click the ▼ next to "Connect" (top-right) → "Change runtime type" → **GPU: L4** (newer than V100, 22.5 GB VRAM).

## Step 1 — Upload training data to Google Drive (10 min)

Move the training data from local → Drive.

```powershell
# Zip locally
Compress-Archive -Path data/synthetic/train.jsonl, data/synthetic/dev.jsonl, data/seeds.jsonl, data/seeds_real.jsonl, backend/prompts/system_prompt.md, backend/prompts/fast_classifier.md -DestinationPath scam-sentinel-data.zip
```

Upload `scam-sentinel-data.zip` to `My Drive/scam-sentinel/` on https://drive.google.com.

## Step 2 — Gemma 3 4B classifier fine-tuning notebook

Create a new notebook → run the cells below in order.

### Cell 1: Verify GPU

```python
!nvidia-smi
```

You should see L4 (22.5 GB) or A100 (40 GB).

### Cell 2: Install Unsloth

```python
!pip install -q unsloth
!pip install -q --upgrade --no-deps "git+https://github.com/unslothai/unsloth.git"
!pip install -q --upgrade transformers trl peft accelerate bitsandbytes
```

### Cell 3: Mount Drive + unzip data

```python
from google.colab import drive
drive.mount('/content/drive')

!mkdir -p /content/scam-sentinel
!unzip -o /content/drive/MyDrive/scam-sentinel/scam-sentinel-data.zip -d /content/scam-sentinel
!ls /content/scam-sentinel/data/synthetic
```

### Cell 4: Load data + convert to classification format

```python
import json
from datasets import Dataset

def load_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f]

train_data = load_jsonl('/content/scam-sentinel/data/synthetic/train.jsonl')
dev_data = load_jsonl('/content/scam-sentinel/data/synthetic/dev.jsonl')

with open('/content/scam-sentinel/backend/prompts/fast_classifier.md') as f:
    fast_prompt = f.read()

# Classification only: short input → just risk_level
def to_classification(rec):
    return {
        "messages": [
            {"role": "system", "content": fast_prompt},
            {"role": "user", "content": f"ANALYZE THIS INPUT:\n\n{rec['text']}"},
            {"role": "assistant", "content": json.dumps({"risk_level": rec["risk_level"]})},
        ]
    }

train_ds = Dataset.from_list([to_classification(r) for r in train_data])
dev_ds = Dataset.from_list([to_classification(r) for r in dev_data])
print(f"Train: {len(train_ds)}, Dev: {len(dev_ds)}")
```

> Verify the training data has a `risk_level` field. If not, derive it from the category (e.g. `normal` → `safe`, `phishing_link` / `bec_scam` / ... → `medium` / `high`).

### Cell 5: Load model (4-bit QLoRA)

```python
from unsloth import FastLanguageModel
import torch

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="google/gemma-3-4b-it",
    max_seq_length=2048,
    load_in_4bit=True,
    dtype=None,  # auto
)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    bias="none", use_gradient_checkpointing="unsloth",
)
```

### Cell 6: Train

```python
from trl import SFTTrainer, SFTConfig

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_ds,
    eval_dataset=dev_ds,
    args=SFTConfig(
        output_dir="/content/outputs/gemma3-classifier",
        per_device_train_batch_size=4,
        gradient_accumulation_steps=4,
        num_train_epochs=1,
        learning_rate=2e-4,
        logging_steps=20,
        eval_strategy="steps",
        eval_steps=100,
        save_steps=200,
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        bf16=True,
        max_seq_length=2048,
        packing=False,
    ),
)
trainer.train()
```

Expected runtime: 30–60 min on L4.

### Cell 7: Save LoRA adapter + back up to Drive

```python
model.save_pretrained("/content/outputs/gemma3-classifier-lora")
tokenizer.save_pretrained("/content/outputs/gemma3-classifier-lora")
!cp -r /content/outputs/gemma3-classifier-lora /content/drive/MyDrive/scam-sentinel/
```

### Cell 8: Convert to GGUF (for Ollama)

```python
model.save_pretrained_gguf(
    "/content/outputs/gemma3-classifier-gguf",
    tokenizer,
    quantization_method="q4_k_m",  # use "q3_k_m" for ~5GB output that fully fits 8GB VRAM
)
!cp /content/outputs/gemma3-classifier-gguf/*.gguf /content/drive/MyDrive/scam-sentinel/
```

## Step 3 — Gemma 4 8B tool-calling fine-tuning notebook

Create a new notebook. Cells 1–3 are identical.

### Cell 4 (changed): full CoT + tool_calls trace

```python
# Training data must contain reasoning + tool_calls.
# If the synthetic data has no reasoning, first self-distill locally with Gemma 4
# to produce a train.jsonl that includes Steps 1–5 reasoning + JSON output.
def to_tool_calling(rec):
    return {
        "messages": [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": f"ANALYZE THIS INPUT:\n\n{rec['text']}"},
            {"role": "assistant", "content": rec["reasoning_with_tools"]},
        ]
    }
```

### Cell 5 (changed)

```python
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="google/gemma-4-8b-it",  # confirm exact HF ID before training
    max_seq_length=4096,
    load_in_4bit=True,
)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj"],
    bias="none", use_gradient_checkpointing="unsloth",
)
```

### Cell 6 (changed — smaller batch)

```python
args=SFTConfig(
    output_dir="/content/outputs/gemma4-toolcalling",
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    num_train_epochs=1,
    learning_rate=1e-4,
    max_seq_length=4096,
    bf16=True,
    ...
)
```

Expected runtime: 2–3 hours on L4.

## Step 4 — Pull adapters/GGUF locally + register with Ollama

```powershell
# After syncing from Drive locally
ollama create scam-sentinel-classifier -f Modelfile-classifier
ollama create scam-sentinel-reasoner -f Modelfile-reasoner
```

Example `Modelfile-classifier`:

```
FROM ./gemma3-classifier-gguf/unsloth.Q4_K_M.gguf
TEMPLATE """{{ .Prompt }}"""
PARAMETER temperature 0.1
PARAMETER num_predict 64
```

Then update `backend/reasoning_agent.py` lines 22–23:

```python
FAST_MODEL = "scam-sentinel-classifier"
DEEP_MODEL = "scam-sentinel-reasoner"
```

## Cost / time summary

| Task | Colab L4 time | Compute units |
|---|---|---|
| Gemma 3 4B classifier | 30–60 min | ~5–10 |
| Gemma 4 8B tool calling | 2–3 hours | ~25–30 |
| Total | ~3–4 hours | ~40 (well within Pro's 100/month) |

## Notes

1. **Avoid session disconnect** — don't close the tab once training starts; an idle/locked screen can trigger an idle disconnect. As a workaround, open a separate tab with `Ctrl+M+Y` to add an empty cell running `import time; time.sleep(60)` as a keepalive.
2. **Save checkpoints often** — `save_steps=200` lets you resume if the session dies mid-training.
3. **Confirm Gemma 4 HF model ID** — `google/gemma-4-8b-it` above is a placeholder. Look up the actual published ID on Hugging Face before training.
4. **Section 12.3 gate** — verify all six Day 11 conditions hold before fine-tuning.
5. **Q3_K_M for local GPU** — to make the fine-tuned model fully fit on the 8 GB 4060 Ti at inference time, set `quantization_method="q3_k_m"` in Cell 8 (output is ~5 GB instead of ~9 GB). Quality drop is minor; speed gain on local GPU is large.
