"""Merge a Gemma 4 QLoRA adapter into its 4-bit base and save 16-bit safetensors.

The base model ships as bnb-4bit, which is not safe to merge into directly
(quantized weights → numerically meaningless deltas). Unsloth re-loads it in
bf16, applies the LoRA delta layer-by-layer (so an 8 GB GPU + system RAM can
handle the ~9.6 GB merged model via auto device_map), and writes a clean
HuggingFace folder ready for `convert_hf_to_gguf.py`.

Run this in WSL2 / Linux. Windows lacks the bitsandbytes + triton compatibility
needed by Unsloth at 4-bit reload time.

Example:
    python scripts/merge_lora.py \\
        --adapter Alice0914/gemma4-e2b-scam-sentinel \\
        --output  /home/alice/scam-models/gemma4-scam-merged
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--adapter",
        default="Alice0914/gemma4-e2b-scam-sentinel",
        help="HuggingFace repo or local path of the LoRA adapter to merge.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Directory to write the merged bf16 safetensors into.",
    )
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=2048,
        help="Max sequence length used during training. Default 2048.",
    )
    args = parser.parse_args()

    try:
        from unsloth import FastLanguageModel
    except ImportError as e:
        print(
            "ERROR: unsloth not installed. Install with:\n"
            '    pip install -U "unsloth @ git+https://github.com/unslothai/unsloth.git" '
            '"transformers>=5.5.1" peft\n',
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"[merge_lora] loading adapter {args.adapter} in bf16 (4-bit base auto-reloaded)…")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.adapter,
        max_seq_length=args.max_seq_length,
        load_in_4bit=False,
        dtype="bfloat16",
    )

    print(f"[merge_lora] merging LoRA → bf16 safetensors at {out}")
    # Unsloth merges the LoRA delta layer-by-layer using device_map="auto",
    # so the full ~9.6 GB model never has to sit in VRAM at once.
    model.save_pretrained_merged(str(out), tokenizer)

    print(f"[merge_lora] done. Next: convert_hf_to_gguf.py {out} --outtype bf16")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
