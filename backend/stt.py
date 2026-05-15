"""
Whisper-base STT for the Scam Sentinel voice demo.

Uses the HuggingFace `automatic-speech-recognition` pipeline so that audio
longer than 30 s is automatically chunked (the default Whisper context length)
and we get real per-chunk timestamps instead of evenly-distributed fake ones.
"""
from __future__ import annotations

import io
import os

# Fix Windows SSL cert path before any HF Hub call
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())
except ImportError:
    pass

import librosa
import torch
from transformers import pipeline

MODEL_ID = "openai/whisper-base"


class WhisperSTT:
    """Long-form Whisper transcriber backed by the HF ASR pipeline."""

    def __init__(self, model_id: str = MODEL_ID) -> None:
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.pipe = pipeline(
            task="automatic-speech-recognition",
            model=model_id,
            torch_dtype=self.dtype,
            device=0 if self.device == "cuda" else -1,
            # Chunk longer audio so we don't lose anything past 30 s, with a
            # short overlap to avoid clipping words at chunk boundaries.
            chunk_length_s=30,
            stride_length_s=(4, 2),
        )

    @torch.no_grad()
    def transcribe(self, audio_bytes: bytes, *, return_segments: bool = False) -> dict:
        """
        Transcribe raw audio bytes (mp3/wav/etc.) and return text + chunk segments.

        Returns:
            {
                "text": str,
                "segments": [{"start": float, "end": float, "text": str}, ...],
                "duration": float,
            }
        """
        audio_arr, _ = librosa.load(io.BytesIO(audio_bytes), sr=16000, mono=True)
        duration = float(len(audio_arr) / 16000.0)

        result = self.pipe(
            audio_arr,
            return_timestamps=True,
            generate_kwargs={"language": "en", "task": "transcribe"},
        )

        text = (result.get("text") or "").strip()
        segments: list[dict] = []

        if return_segments:
            raw_chunks = result.get("chunks") or []
            for chunk in raw_chunks:
                ts = chunk.get("timestamp") or (None, None)
                start, end = ts[0], ts[1]
                if start is None:
                    continue
                if end is None or end <= start:
                    end = min(start + 4.0, duration)
                phrase = (chunk.get("text") or "").strip()
                if not phrase:
                    continue
                segments.append({
                    "start": round(float(start), 2),
                    "end": round(min(float(end), duration), 2),
                    "text": phrase,
                })

            # Always resplit so the UI shows short on-screen phrases,
            # even when Whisper returned long chunk-level timestamps.
            if segments:
                segments = _resplit_long_chunks(segments, text, duration)

            # Last fallback if pipeline returned no timestamps at all
            if not segments:
                segments = _even_split(text, duration)

        return {"text": text, "segments": segments, "duration": duration}


def _resplit_long_chunks(segments: list[dict], text: str, duration: float) -> list[dict]:
    """If we only got one or two huge chunks, break them into shorter phrases."""
    import re

    if not segments:
        return _even_split(text, duration)

    new: list[dict] = []
    for seg in segments:
        seg_text = seg["text"]
        seg_start, seg_end = seg["start"], seg["end"]
        seg_duration = max(0.1, seg_end - seg_start)

        # Split on commas, semicolons, dashes, conjunctions, and sentence ends
        parts = re.split(
            r"(?<=[.!?,;:—–])\s+|\s+(?:and|but|so|because|or)\s+",
            seg_text,
        )
        parts = [p.strip(" ,;:—–") for p in parts if p.strip()]

        # Hard cap any remaining long parts at 6 words
        fine: list[str] = []
        for p in parts:
            words = p.split()
            if len(words) <= 8:
                fine.append(p)
            else:
                for i in range(0, len(words), 6):
                    fine.append(" ".join(words[i : i + 6]))

        if not fine:
            new.append(seg)
            continue

        weights = [max(1, len(p)) for p in fine]
        total = sum(weights)
        cursor = seg_start
        for piece, w in zip(fine, weights):
            chunk_duration = seg_duration * (w / total)
            start = cursor
            end = min(cursor + chunk_duration, seg_end)
            new.append({"start": round(start, 2), "end": round(end, 2), "text": piece})
            cursor = end
    return new


def _even_split(text: str, duration: float) -> list[dict]:
    """Pure fallback when Whisper returns no timestamps at all."""
    import re

    parts = re.split(r"(?<=[.!?,;:])\s+|\s+(?:and|but|so|because|or)\s+", text.strip())
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return [{"start": 0.0, "end": duration, "text": text.strip()}]

    weights = [max(1, len(p)) for p in parts]
    total = sum(weights)
    segments = []
    cursor = 0.0
    for p, w in zip(parts, weights):
        seg_duration = duration * (w / total)
        start = cursor
        end = min(cursor + seg_duration, duration)
        segments.append({"start": round(start, 2), "end": round(end, 2), "text": p})
        cursor = end
    return segments
