"""
Quick test: Whisper-base STT on local GPU.

Generates a short TTS audio clip with a fake scam sentence, then
transcribes it with Whisper-base (142 MB).

Run:
    python scripts/try_whisper_audio.py
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
print("WHISPER-BASE STT - PROOF OF CONCEPT")
print("=" * 60)

# ---------------------------------------------------------------
# Step 1: generate / reuse a scam-style audio clip with gTTS
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

if not mp3_path.exists():
    scam_text = (
        "Grandma, it's me, Tyler. I'm in jail. "
        "I need you to send five thousand dollars right now. "
        "Please don't tell Mom. The bank account is new."
    )
    gTTS(scam_text, lang="en").save(str(mp3_path))
    print(f"  Saved: {mp3_path}")
else:
    print(f"  Reusing existing: {mp3_path}")

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
# Step 3: load Whisper-base
# ---------------------------------------------------------------
print("\n[3/4] Loading Whisper-base (~142 MB)...")
import torch
from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq

MODEL_ID = "openai/whisper-base"

t0 = time.time()
processor = AutoProcessor.from_pretrained(MODEL_ID)
print(f"  Processor loaded in {time.time()-t0:.1f}s")

t0 = time.time()
model = AutoModelForSpeechSeq2Seq.from_pretrained(
    MODEL_ID,
    dtype=torch.float16,
    device_map="cuda:0",
)
model.eval()
print(f"  Model loaded in {time.time()-t0:.1f}s")
print(f"  GPU mem allocated: {torch.cuda.memory_allocated()/1e9:.2f} GB")

# ---------------------------------------------------------------
# Step 4: transcribe
# ---------------------------------------------------------------
print("\n[4/4] Transcribing audio...")

inputs = processor(
    audio,
    sampling_rate=16000,
    return_tensors="pt",
).to(model.device, dtype=torch.float16)

t0 = time.time()
with torch.no_grad():
    predicted_ids = model.generate(
        inputs["input_features"],
        max_new_tokens=256,
        language="en",
        task="transcribe",
    )
gen_time = time.time() - t0

transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

print(f"  Transcribed in {gen_time:.2f}s")
print("\n" + "=" * 60)
print("WHISPER TRANSCRIPT:")
print("=" * 60)
print(transcription.strip())
print("=" * 60)

audio_duration = len(audio) / sr
realtime_factor = gen_time / audio_duration
print(f"\nAudio: {audio_duration:.1f}s, Transcribe: {gen_time:.2f}s -> {realtime_factor:.2f}x real-time")
print(f"GPU mem: {torch.cuda.memory_allocated()/1e9:.2f} GB / {torch.cuda.get_device_properties(0).total_memory/1e9:.2f} GB")
