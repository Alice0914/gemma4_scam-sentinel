"""
Alternative LoRA fine-tuning entry point (PEFT + transformers, Windows-friendly).

NOTE: This is NOT the path that produced the shipped production model.
The production fine-tune (Gemma 4 E2B + QLoRA, F1 86.1% / FPR 1.1%) was
trained via Unsloth on Colab Pro L4 — see `finetune_gemma4_e2b.ipynb`.
This script remains as a fallback / reference for the Gemma 3 4B base
and for users without Unsloth + GPU access. Override `--model` to target
a different base.

Usage:
    python scripts/train_lora.py
    python scripts/train_lora.py --max-samples 500  # quick smoke run
    python scripts/train_lora.py --model google/gemma-4-E2B-it  # alt base
"""

import json
import argparse
from pathlib import Path


def load_dataset(path: Path, max_samples: int | None = None):
    from datasets import Dataset
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    if max_samples:
        samples = samples[:max_samples]
    return Dataset.from_list(samples)


def format_sample(example, tokenizer):
    text = tokenizer.apply_chat_template(
        example["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="google/gemma-3-4b-it")
    parser.add_argument("--train", type=Path, default=Path("data/synthetic/train_chat.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("models/gemma3-4b-lora"))
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--max-samples", type=int, default=None)
    args = parser.parse_args()

    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, TrainingArguments
    from peft import LoraConfig, get_peft_model, TaskType
    from trl import SFTTrainer

    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

    # 4-bit quantization config
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    print(f"Loading {args.model}...")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model.config.use_cache = False

    # LoRA config
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules="all-linear",
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    print("Loading dataset...")
    dataset = load_dataset(args.train, args.max_samples)
    dataset = dataset.map(lambda x: format_sample(x, tokenizer), remove_columns=["messages"])
    print(f"Training on {len(dataset)} samples")

    training_args = TrainingArguments(
        output_dir=str(args.output / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        warmup_ratio=0.03,
        learning_rate=2e-4,
        bf16=True,
        logging_steps=20,
        save_strategy="epoch",
        optim="paged_adamw_8bit",
        lr_scheduler_type="cosine",
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=1024,
        args=training_args,
    )

    print("Starting LoRA training...")
    trainer.train()

    print(f"Saving adapter to {args.output}...")
    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(args.output))
    tokenizer.save_pretrained(str(args.output))
    print("Training complete.")


if __name__ == "__main__":
    main()
