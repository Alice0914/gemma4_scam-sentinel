"""
Quick test: does Gemma 3n E2B accept audio input via transformers?

Gemma 3n is designed for edge/mobile — ~2 GB memory footprint —
so it should fit on an 8 GB GPU without CPU offload.

Generates a short TTS audio clip with a fake scam sentence, then asks
Gemma 3n to transcribe + analyze it in one shot.

Run:
    python scripts/try_gemma_audio.py
"""
import os
import sys
import time
from pathlib import Path

# Fix Windows SSL cert path before any HF Hub call
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    os.environ["CURL_CA_BUNDLE"] = certifi.where()
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "certifi"])
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    os.environ["CURL_CA_BUNDLE"] = certifi.where()

print("=" * 60)
print("GEMMA 3n E2B AUDIO INPUT - PROOF OF CONCEPT")
print("=" * 60)

# ---------------------------------------------------------------
# Step 1: generate a tiny scam-style audio clip with gTTS
# ---------------------------------------------------------------
print("\n[1/4] Generating test audio with gTTS...")
try:
    from gtts import gTTS
except ImportError:
    print("  Installing gtts...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "gtts"])
    from gtts import gTTS

audio_dir = Path("results/local_eval")
audio_dir.mkdir(parents=True, exist_ok=True)
mp3_path = audio_dir / "test_call.mp3"

scam_text = (
    "Grandma, it's me, Tyler. I'm in jail. "
    "I need you to send five thousand dollars right now. "
    "Please don't tell Mom. The bank account is new."
)
gTTS(scam_text, lang="en").save(str(mp3_path))
print(f"  Saved: {mp3_path}")

# ---------------------------------------------------------------
# Step 2: load audio as 16kHz mono numpy array
# ---------------------------------------------------------------
print("\n[2/4] Loading audio as 16kHz mono...")
try:
    import librosa
except ImportError:
    print("  Installing librosa...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "librosa"])
    import librosa

audio, sr = librosa.load(str(mp3_path), sr=16000, mono=True)
print(f"  Audio shape: {audio.shape}, sample rate: {sr}, duration: {len(audio)/sr:.1f}s")

# ---------------------------------------------------------------
# Step 3: load Gemma 3n E2B with audio-capable processor
# ---------------------------------------------------------------
print("\n[3/4] Loading Gemma 3n E2B + processor (~2 GB footprint, no quant needed)...")
import torch
from transformers import AutoProcessor, AutoModelForImageTextToText

MODEL_ID = "unsloth/gemma-3n-E2B-it-unsloth-bnb-4bit"  # pre-quantized 4-bit (~2.5 GB)

t0 = time.time()
processor = AutoProcessor.from_pretrained(MODEL_ID)
print(f"  Processor loaded in {time.time()-t0:.1f}s")
print(f"  Processor type: {type(processor).__name__}")

t0 = time.time()
# Gemma 3n is small enough to load in bf16 directly on 8 GB GPU
model = AutoModelForImageTextToText.from_pretrained(
    MODEL_ID,
    dtype=torch.bfloat16,
    device_map="cuda:0",
)
model.eval()
print(f"  Model loaded in {time.time()-t0:.1f}s")
print(f"  Model class: {type(model).__name__}")
print(f"  GPU mem allocated: {torch.cuda.memory_allocated()/1e9:.2f} GB")

# ---------------------------------------------------------------
# Step 4: send audio + prompt, get text out
# ---------------------------------------------------------------
print("\n[4/4] Running inference (audio + prompt -> text)...")

messages = [
    {
        "role": "user",
        "content": [
            {"type": "audio", "audio": audio},
            {
                "type": "text",
                "text": (
                    "Transcribe the spoken audio above word-for-word, then on a new line "
                    "say whether it looks like a scam (yes/no) and briefly why."
                ),
            },
        ],
    }
]

try:
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    ).to(model.device, dtype=torch.bfloat16)
except Exception as e:
    print(f"  apply_chat_template failed: {e}")
    print("  Trying processor(...) direct call instead...")
    inputs = processor(audio=audio, text=messages[0]["content"][1]["text"], return_tensors="pt").to(model.device)

t0 = time.time()
with torch.no_grad():
    outputs = model.generate(
        **inputs,
        max_new_tokens=256,
        do_sample=False,
    )
gen_time = time.time() - t0

# Strip input tokens from output
new_tokens = outputs[0, inputs["input_ids"].shape[1]:]
response = processor.decode(new_tokens, skip_special_tokens=True)

print(f"  Generated in {gen_time:.1f}s, {new_tokens.shape[0]} tokens")
print("\n" + "=" * 60)
print("MODEL OUTPUT:")
print("=" * 60)
print(response)
print("=" * 60)
print("\nDONE - audio input is supported." if response.strip() else "\nEMPTY OUTPUT - audio path may not be wired correctly.")
print(f"\nFinal GPU mem: {torch.cuda.memory_allocated()/1e9:.2f} GB / {torch.cuda.get_device_properties(0).total_memory/1e9:.2f} GB")
