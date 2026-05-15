"""
Scam Sentinel FastAPI backend.
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.reasoning_agent import (
    ScamReasoningAgent,
    SignalInput,
    AgentOutput,
    FAST_MODEL,
    DEEP_MODEL,
)

FEEDBACK_PATH = Path("data/user_feedback.jsonl")


# --- Lifespan: load agent + STT + fine-tuned model once at startup ---

agent: ScamReasoningAgent | None = None
stt = None  # type: ignore[assignment]
finetuned = None  # type: ignore[assignment]

# In-memory accumulated transcript per call session (cleared on backend restart)
voice_sessions: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent, stt, finetuned
    from pathlib import Path

    rag_retriever = None
    if Path("data/vector_store").exists():
        from backend.rag import ScamCaseRetriever
        rag_retriever = ScamCaseRetriever(top_k=3)

    # Try loading the local fine-tuned Gemma 4 (transformers + PEFT, 4-bit).
    # If anything fails (no GPU, bnb broken, network), Stage 2 falls back
    # to Ollama gemma4 automatically.
    try:
        from backend.finetuned_agent import FineTunedAgent
        finetuned = FineTunedAgent()
        print(f"[startup] Fine-tuned Gemma 4 + QLoRA loaded on {finetuned.device}")
    except Exception as e:
        print(f"[startup] Fine-tuned model unavailable, Stage 2 will use Ollama gemma4: {e}")
        finetuned = None

    agent = ScamReasoningAgent(
        rag_retriever=rag_retriever,
        finetuned_agent=finetuned,
    )

    # Lazy-load Whisper only if available; keeps backend usable without GPU
    try:
        from backend.stt import WhisperSTT
        stt = WhisperSTT()
        print(f"[startup] Whisper loaded on {stt.device}")
    except Exception as e:
        print(f"[startup] Whisper unavailable: {e}")
        stt = None

    yield
    agent = None
    stt = None
    finetuned = None


app = FastAPI(title="Scam Sentinel API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request / Response models ---

class AnalyzeTextRequest(BaseModel):
    text: str
    channel: str = "sms"
    metadata: dict | None = None


class AnalyzeVoiceRequest(BaseModel):
    transcript: str
    voice_signals: dict | None = None
    metadata: dict | None = None


class FeedbackRequest(BaseModel):
    input_text: str
    channel: str
    predicted_risk: str
    predicted_patterns: list[str] = []
    tool_calls: list[dict] = []
    user_verdict: str  # "correct" | "false_alarm"
    user_message_excerpt: str = ""


# --- Endpoints ---

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "architecture": "single_model",
        "reasoning_model": (
            "Alice0914/gemma4-e2b-scam-sentinel (transformers+PEFT, 4-bit)"
            if finetuned is not None
            else f"{DEEP_MODEL} (Ollama, merged QLoRA → Q4_K_M GGUF)"
        ),
        "stt": "whisper-base" if stt is not None else "unavailable",
    }


@app.post("/analyze/text", response_model=AgentOutput)
async def analyze_text(req: AnalyzeTextRequest):
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    signals = SignalInput(
        text=req.text,
        channel=req.channel,
        metadata=req.metadata,
    )
    # Single-model architecture (no cascade): every request goes directly to
    # the fine-tuned Gemma 4 (or Ollama gemma4 fallback). Self-consistency off
    # for demo responsiveness.
    return agent.analyze(signals, use_self_consistency=False, use_cascade=False)


@app.post("/analyze/voice", response_model=AgentOutput)
async def analyze_voice(req: AnalyzeVoiceRequest):
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    signals = SignalInput(
        transcript=req.transcript,
        voice_signals=req.voice_signals,
        metadata=req.metadata,
        channel="voice",
    )
    return agent.analyze(signals, use_self_consistency=False, use_cascade=False)


@app.post("/analyze/voice_chunk")
async def analyze_voice_chunk(
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    reset: str = Form("false"),
):
    """
    Live-call demo endpoint.

    Each call sends one audio chunk (typically the most recent ~10s of playback)
    plus a session_id. The backend:
      1. Transcribes the chunk with Whisper-base.
      2. Appends the chunk's transcript to the session's running transcript.
      3. Runs the full running transcript through the scam reasoning agent.
      4. Returns the new chunk text, the running transcript, and the latest verdict.

    Set reset=true on the first chunk of a new call to clear the buffer.
    """
    if stt is None:
        raise HTTPException(status_code=503, detail="Whisper STT not available on this server")
    if agent is None:
        raise HTTPException(status_code=503, detail="Reasoning agent not initialized")

    if reset.lower() == "true":
        voice_sessions[session_id] = ""

    audio_bytes = await audio.read()
    result = stt.transcribe(audio_bytes, return_segments=False)
    chunk_text = result["text"].strip()

    running = (voice_sessions.get(session_id, "") + " " + chunk_text).strip()
    voice_sessions[session_id] = running

    # Analyze cumulative transcript via the existing voice channel
    signals = SignalInput(
        transcript=running,
        metadata={"channel": "voice", "session_id": session_id},
        channel="voice",
    )
    analysis = agent.analyze(signals, use_self_consistency=False, use_cascade=False)

    return {
        "session_id": session_id,
        "chunk_transcript": chunk_text,
        "running_transcript": running,
        "chunk_duration": result["duration"],
        "analysis": analysis,
    }


VOICE_CACHE_DIR = Path("results/local_eval/voice_cache")
VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/analyze/voice_full")
async def analyze_voice_full(audio: UploadFile = File(...)):
    """
    Single-shot variant: transcribe the entire audio file + analyze once.
    Results are cached by audio content hash so demo replays are instant.
    """
    import hashlib

    if stt is None:
        raise HTTPException(status_code=503, detail="Whisper STT not available on this server")
    if agent is None:
        raise HTTPException(status_code=503, detail="Reasoning agent not initialized")

    audio_bytes = await audio.read()
    audio_hash = hashlib.sha256(audio_bytes).hexdigest()[:16]
    cache_path = VOICE_CACHE_DIR / f"{audio_hash}.json"

    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as f:
            cached = json.load(f)
        cached["_cache_hit"] = True
        return cached

    result = stt.transcribe(audio_bytes, return_segments=True)

    signals = SignalInput(
        transcript=result["text"],
        metadata={"channel": "voice"},
        channel="voice",
    )
    analysis = agent.analyze(signals, use_self_consistency=False, use_cascade=False)

    payload = {
        "transcript": result["text"],
        "segments": result["segments"],
        "duration": result["duration"],
        "analysis": analysis.model_dump() if hasattr(analysis, "model_dump") else analysis,
        "_cache_hit": False,
    }
    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return payload


@app.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """
    Self-Improving Cascade entry point.

    Appends one JSON line per 👍/👎 click. The file feeds two downstream loops:
      A. Constitutional Self-Critique (daily)  — false_alarm entries drive prompt revisions.
      B. DPO Preference Pairs (weekly/manual)  — both verdicts build preference pairs.
    """
    if req.user_verdict not in ("correct", "false_alarm"):
        raise HTTPException(status_code=400, detail="user_verdict must be 'correct' or 'false_alarm'")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **req.model_dump(),
    }
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"status": "recorded", "verdict": req.user_verdict}
