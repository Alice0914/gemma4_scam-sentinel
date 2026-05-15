"""DPO fine-tuning on user feedback (Loop B of the Self-Improving Cascade).

Starts from the existing SFT adapter (`Alice0914/gemma4-e2b-scam-sentinel`) and
applies a short DPO pass over the preference pairs built by
`scripts/build_dpo_pairs.py`. The result is a NEW LoRA adapter that prefers the
chosen responses over the rejected ones — i.e. less false-alarm yelling and
less missed-scam silence.

Run in WSL2 / Linux on a GPU. ~5 minutes for a few hundred pairs on an L4 or
RTX 4060 Ti; longer if the pair count grows.

Example:
    python scripts/train_dpo.py \\
        --pairs data/dpo_pairs.jsonl \\
        --output models/gemma4-e2b-scam-dpo

The output folder contains the new LoRA adapter. Push to HF or merge + GGUF
the same way as the SFT adapter to deploy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pairs", type=Path, default=Path("data/dpo_pairs.jsonl"))
    p.add_argument("--base-adapter", default="Alice0914/gemma4-e2b-scam-sentinel",
                   help="SFT adapter to start DPO from. Default: the published checkpoint.")
    p.add_argument("--output", type=Path, default=Path("models/gemma4-e2b-scam-dpo"))
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--lr", type=float, default=5e-6,
                   help="DPO uses a much lower LR than SFT. Default 5e-6.")
    p.add_argument("--beta", type=float, default=0.1,
                   help="DPO temperature. Higher = closer to reference, lower = more aggressive.")
    p.add_argument("--max-seq-length", type=int, default=2048)
    args = p.parse_args()

    if not args.pairs.exists():
        print(f"ERROR: no preference pairs at {args.pairs}. Run scripts/build_dpo_pairs.py first.",
              file=sys.stderr)
        return 1

    try:
        from unsloth import FastLanguageModel, PatchDPOTrainer
        from datasets import Dataset
        from trl import DPOTrainer, DPOConfig
    except ImportError as e:
        print(
            "ERROR: missing deps. Install with:\n"
            '    pip install -U "unsloth @ git+https://github.com/unslothai/unsloth.git" '
            '"transformers>=5.5.1" "trl>=0.12" peft datasets\n',
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    # Unsloth's DPO patch enables their fast kernels inside DPOTrainer.
    PatchDPOTrainer()

    # Load pairs. The conversational format ({prompt, chosen, rejected} as
    # role/content lists) is the format DPOTrainer understands natively when
    # the tokenizer has a chat template.
    rows: list[dict] = []
    with args.pairs.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            # Strip metadata keys; DPOTrainer only wants prompt/chosen/rejected.
            rows.append({k: rec[k] for k in ("prompt", "chosen", "rejected")})
    if not rows:
        print("ERROR: pairs file is empty.", file=sys.stderr)
        return 1
    dataset = Dataset.from_list(rows)
    print(f"[train_dpo] loaded {len(dataset)} preference pairs")

    # Re-load the SFT adapter in 4-bit. Unsloth handles bnb + LoRA wiring.
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_adapter,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
        dtype="bfloat16",
    )

    # Re-attach LoRA adapters trainable for DPO. We use the same target modules
    # as SFT so the new preference signal flows through the same parameters.
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.0,
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cfg = DPOConfig(
        output_dir=str(args.output),
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=4,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        beta=args.beta,
        max_length=args.max_seq_length,
        max_prompt_length=args.max_seq_length // 2,
        bf16=True,
        logging_steps=5,
        save_strategy="no",
        report_to="none",
        remove_unused_columns=False,
    )

    trainer = DPOTrainer(
        model=model,
        ref_model=None,  # PEFT-style: ref = base + frozen adapter, handled internally.
        args=cfg,
        train_dataset=dataset,
        tokenizer=tokenizer,
    )

    print(f"[train_dpo] starting DPO: {args.epochs} epoch(s), lr={args.lr}, beta={args.beta}")
    trainer.train()

    print(f"[train_dpo] saving adapter to {args.output}")
    model.save_pretrained(str(args.output))
    tokenizer.save_pretrained(str(args.output))
    print("[train_dpo] done.")
    print("[train_dpo] next: merge + GGUF the same way as the SFT adapter — see README §Deploying the fine-tuned model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
