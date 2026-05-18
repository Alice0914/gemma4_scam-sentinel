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
    DEEP_MODEL,
)

FEEDBACK_PATH = Path("data/user_feedback.jsonl")


# --- Lifespan: load agent + STT + fine-tuned model once at startup ---

agent: ScamReasoningAgent | None = None
stt = None  # type: ignore[assignment]
finetuned = None  # type: ignore[assignment]
RAG_ENABLED: bool = False  # populated by lifespan(); read by analyze endpoints

# In-memory accumulated transcript per call session (cleared on backend restart)
voice_sessions: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent, stt, finetuned, RAG_ENABLED
    import os
    from pathlib import Path

    # RAG is OFF by default — the 300-sample eval showed retrieved FTC cases
    # bias the model toward false positives on conversational ham. Set
    # SCAM_SENTINEL_RAG=1 to enable retrieval; the vector_store index must
    # also exist on disk.
    rag_retriever = None
    rag_requested = os.environ.get("SCAM_SENTINEL_RAG", "0") == "1"
    if rag_requested and Path("data/vector_store").exists():
        from backend.rag import ScamCaseRetriever
        rag_retriever = ScamCaseRetriever(top_k=3)
        RAG_ENABLED = True
        print("[startup] RAG enabled (SCAM_SENTINEL_RAG=1, index found).")
    elif rag_requested:
        RAG_ENABLED = False
        print("[startup] RAG requested but data/vector_store missing — disabled.")
    else:
        RAG_ENABLED = False
        print("[startup] RAG disabled (default). Set SCAM_SENTINEL_RAG=1 to enable.")

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
        "rag": "enabled" if RAG_ENABLED else "disabled (default)",
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
    return agent.analyze(signals, use_self_consistency=False, use_cascade=False, use_rag=RAG_ENABLED)


@app.post("/analyze/image", response_model=AgentOutput)
async def analyze_image(image: UploadFile = File(...)):
    """
    OCR an uploaded MMS-style scam screenshot via pytesseract, then route the
    extracted text through the same analyzer the text channel uses. The
    extracted text is also stored in metadata so the model can fire the
    verify_image_message tool.
    """
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        import io
        from PIL import Image
        import pytesseract
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"OCR deps missing — install pytesseract + Pillow: {e}",
        )

    # On Windows, pytesseract only looks at PATH by default. winget / the
    # UB-Mannheim installer drops the binary in a standard location that the
    # parent shell often hasn't picked up yet, so probe a few well-known paths.
    if not pytesseract.pytesseract.tesseract_cmd or pytesseract.pytesseract.tesseract_cmd == "tesseract":
        import shutil as _shutil
        candidates = [
            _shutil.which("tesseract"),
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/opt/homebrew/bin/tesseract",
        ]
        for path in candidates:
            if path and Path(path).exists():
                pytesseract.pytesseract.tesseract_cmd = path
                break

    image_bytes = await image.read()
    try:
        pil_img = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not open image: {e}")

    try:
        extracted_text = pytesseract.image_to_string(pil_img).strip()
    except pytesseract.TesseractNotFoundError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Tesseract binary not found. Install it: "
                "Windows → https://github.com/UB-Mannheim/tesseract/wiki ; "
                "macOS → `brew install tesseract` ; "
                "Linux → `apt install tesseract-ocr`."
            ),
        )

    if not extracted_text:
        # No readable text — return a synthetic safe verdict so the UI does not crash.
        return AgentOutput(
            risk_level="safe",
            patterns=[],
            user_message="No readable text was found in the image.",
            tool_calls=[],
            tool_results=[],
            raw_reasoning="ocr_empty",
        )

    signals = SignalInput(
        text=extracted_text,
        channel="sms",
        metadata={
            "image_extracted_text": extracted_text,
            "image_source": image.filename or "uploaded_image",
        },
    )
    return agent.analyze(signals, use_self_consistency=False, use_cascade=False, use_rag=RAG_ENABLED)


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
    return agent.analyze(signals, use_self_consistency=False, use_cascade=False, use_rag=RAG_ENABLED)


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
    analysis = agent.analyze(signals, use_self_consistency=False, use_cascade=False, use_rag=RAG_ENABLED)

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
    analysis = agent.analyze(signals, use_self_consistency=False, use_cascade=False, use_rag=RAG_ENABLED)

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
