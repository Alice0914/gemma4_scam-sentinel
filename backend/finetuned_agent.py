"""
Local inference for the fine-tuned Gemma 4 E2B + QLoRA adapter.

OPTIONAL FALLBACK PATH. Production runs the model through Ollama
(`gemma4-scam`, merged + Q4_K_M GGUF) — see backend/reasoning_agent.py.
This module is only loaded when Ollama is unavailable, or for parity
testing against the in-process PEFT path. backend/main.py wraps the
import in try/except and silently falls back to Ollama on any failure
(typical on Windows because of bitsandbytes / triton compatibility).

Loads `Alice0914/gemma4-e2b-scam-sentinel` (LoRA adapter) on top of the
matching `unsloth/gemma-4-E2B-it-unsloth-bnb-4bit` (pre-quantized 4-bit
base) via Unsloth. The whole stack is already 4-bit so it fits in
~3.5 GB VRAM.
"""
from __future__ import annotations

import os
import threading
from typing import Optional

# Fix Windows/WSL SSL cert path before any HF Hub call.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())
except ImportError:
    pass

import torch

ADAPTER_ID = "Alice0914/gemma4-e2b-scam-sentinel"


class FineTunedAgent:
    """4-bit pre-quantized base + bf16 LoRA adapter, loaded once at startup."""

    def __init__(self, adapter_id: str = ADAPTER_ID) -> None:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU required for FineTunedAgent")

        self.device = "cuda:0"
        from unsloth import FastLanguageModel

        # Adapter's adapter_config.json already points at
        # `unsloth/gemma-4-E2B-it-unsloth-bnb-4bit` (pre-quantized 4-bit base),
        # so Unsloth's default `load_in_4bit=True` reuses that quantization
        # without re-quantizing fp16 encoders. Fits in ~3.5 GB VRAM.
        self.model, self.tokenizer = FastLanguageModel.from_pretrained(
            model_name=adapter_id,
            max_seq_length=1024,
            load_in_4bit=True,
            dtype=torch.bfloat16,
        )
        FastLanguageModel.for_inference(self.model)
        self.model.eval()
        # Serialize concurrent /analyze calls.
        self._lock = threading.Lock()

    @torch.no_grad()
    def generate(
        self,
        system_prompt: str,
        user_message: str,
        *,
        temperature: float = 0.3,
        max_new_tokens: int = 1024,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"ANALYZE THIS INPUT:\n\n{user_message}"},
        ]
        prompt_text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
        )
        inputs = self.tokenizer(text=prompt_text, return_tensors="pt").to(self.device)

        with self._lock:
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=temperature > 0.0,
                top_p=0.9,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        gen = outputs[0, inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(gen, skip_special_tokens=True).strip()


_singleton: Optional[FineTunedAgent] = None


def get_or_load() -> FineTunedAgent:
    global _singleton
    if _singleton is None:
        _singleton = FineTunedAgent()
    return _singleton
