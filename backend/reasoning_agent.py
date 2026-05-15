"""
Scam Sentinel reasoning agent.
Wraps Gemma 4 (via Ollama) with system prompt, RAG context, and function calling.
"""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel

from backend.tools import execute_tool_call, ToolResult

OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

# Hybrid cascade: a fast small model decides "is this safe?" and a deep model
# does the plain-language reasoning + function calling only when needed.
FAST_MODEL = "gemma3:4b"
DEEP_MODEL = "gemma4-scam"

SYSTEM_PROMPT_PATH = Path("backend/prompts/system_prompt.md")
FAST_CLASSIFIER_PROMPT_PATH = Path("backend/prompts/fast_classifier.md")


# ── Helpers for tool inference ────────────────────────────────────────────────

_URL_RE = re.compile(
    r"\b(?:https?://|www\.)?[a-z0-9][a-z0-9.\-]*\.(?:com|net|org|co|co\.uk|xyz|top|info|biz|club|tk|ml|gq|app|io)(?:/[^\s)]*)?",
    re.IGNORECASE,
)

_BRAND_KEYWORDS = {
    "chase":           ["chase", "jpmc"],
    "usps":            ["usps", "us postal", "postal service"],
    "irs":             ["irs", "internal revenue"],
    "amazon":          ["amazon"],
    "fedex":           ["fedex", "fed ex"],
    "ups":             ["ups", "united parcel"],
    "paypal":          ["paypal"],
    "wells fargo":     ["wells fargo", "wellsfargo"],
    "social security": ["social security", "ssa", "ssn"],
    "bank of america": ["bank of america", "bofa"],
}

_RED_PHRASE_PATTERNS = [
    r"send\s+\$?\d", r"wire\s+transfer", r"bitcoin", r"gift\s+card",
    r"don'?t\s+tell", r"keep\s+(this\s+)?(between\s+us|secret|confidential)",
    r"right\s+now", r"within\s+the\s+hour", r"act\s+(now|fast|immediately)",
    r"my\s+phone\s+is\s+broken", r"can'?t\s+talk", r"don'?t\s+call",
    r"verify\s+(your\s+)?(account|identity|password|otp|pin)",
    r"new\s+(bank\s+)?account", r"social\s+security",
    r"click\s+(here|the\s+link)", r"redelivery\s+fee",
]


def _extract_url(text: str) -> str | None:
    if not text:
        return None
    m = _URL_RE.search(text)
    if not m:
        return None
    raw = m.group(0).strip().rstrip(".,;:)")
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    return raw


def _detect_impersonated_brand(text: str) -> str | None:
    if not text:
        return None
    t = text.lower()
    for brand, kws in _BRAND_KEYWORDS.items():
        if any(kw in t for kw in kws):
            return brand
    return None


def _extract_red_phrases(text: str, max_n: int = 4) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for pat in _RED_PHRASE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            found.append(m.group(0))
        if len(found) >= max_n:
            break
    return found


# --- I/O models ---

class SignalInput(BaseModel):
    text: str | None = None
    transcript: str | None = None
    voice_signals: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    channel: str = "sms"  # sms | email | voice


class AgentOutput(BaseModel):
    risk_level: str
    patterns: list[str]
    user_message: str
    tool_calls: list[dict]
    tool_results: list[dict]
    raw_reasoning: str


# --- Agent ---

class ScamReasoningAgent:
    def __init__(self, rag_retriever=None, finetuned_agent=None):
        self.system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        self.fast_classifier_prompt = FAST_CLASSIFIER_PROMPT_PATH.read_text(encoding="utf-8")
        self.rag_retriever = rag_retriever  # optional, injected at startup
        # If a local fine-tuned model is loaded, Stage 2 routes there instead
        # of Ollama. Falls back to Ollama gemma4 if not provided.
        self.finetuned_agent = finetuned_agent

    def _build_user_message(self, signals: SignalInput, similar_cases: list[dict]) -> str:
        parts = []

        if signals.transcript:
            parts.append(f"TRANSCRIPT: {signals.transcript}")
        if signals.text:
            parts.append(f"TEXT: {signals.text}")
        if signals.voice_signals:
            parts.append(f"VOICE_SIGNALS: {json.dumps(signals.voice_signals)}")
        if signals.metadata:
            parts.append(f"METADATA: {json.dumps(signals.metadata)}")

        user_msg = "\n".join(parts)

        if similar_cases:
            user_msg += "\n\nSIMILAR PAST CASES (for reference, not training):\n"
            for i, case in enumerate(similar_cases, 1):
                user_msg += (
                    f"[Case {i}] {case.get('title', '')}, {case.get('year', '')}\n"
                    f"  Summary: {case.get('summary', '')}\n"
                    f"  Outcome: {case.get('outcome', '')}\n"
                )
            user_msg += "\nIf the current input matches a known pattern from these cases, mention it in user_message."

        return user_msg

    def _call_ollama(
        self,
        user_message: str,
        temperature: float = 0.3,
        model: str = DEEP_MODEL,
        system_prompt: str | None = None,
        num_predict: int = 1024,
    ) -> str:
        """Single chat completion.

        Routing rule:
          * If `model == DEEP_MODEL` AND a local fine-tuned agent is available,
            run inference locally via transformers + PEFT (Path B).
          * Otherwise (Stage 1 fast classifier, or fine-tune unavailable),
            fall back to the Ollama HTTP API.
        """
        if model == DEEP_MODEL and self.finetuned_agent is not None:
            return self.finetuned_agent.generate(
                system_prompt=system_prompt or self.system_prompt,
                user_message=user_message,
                temperature=temperature,
                max_new_tokens=num_predict,
            )

        options: dict[str, Any] = {
            "temperature": temperature,
            "num_predict": num_predict,
            "top_p": 0.9,
            "repeat_penalty": 1.2,
        }
        # Deep model (fine-tuned gemma4-scam, E2B Q4_K_M ≈ 3.2GB) fits fully on
        # an 8GB 4060 Ti — leave GPU offload at Ollama defaults. Context window
        # is already set to 4096 in the Modelfile.
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt or self.system_prompt},
                {"role": "user", "content": f"ANALYZE THIS INPUT:\n\n{user_message}"},
            ],
            "stream": False,
            "options": options,
        }
        resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=600)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()

    # ── Stage 1: fast classifier (Gemma 3) ──────────────────────────────
    _FAST_RISK_RE = re.compile(
        r'"risk_level"\s*:\s*"(safe|low|medium|high|critical)"',
        re.IGNORECASE,
    )

    def _fast_classify(self, signals: SignalInput) -> tuple[str, str]:
        """
        Run a tiny Gemma 3 pass that returns ONLY a risk_level.
        No RAG, no self-consistency, low max tokens — designed for ~1s latency.
        Returns (risk_level, raw_text).
        """
        user_msg = self._build_user_message(signals, similar_cases=[])
        try:
            raw = self._call_ollama(
                user_msg,
                temperature=0.1,
                model=FAST_MODEL,
                system_prompt=self.fast_classifier_prompt,
                num_predict=64,
            )
        except Exception as e:
            # If the fast model fails, fall through to the deep model.
            return "unknown", f"fast_classifier_error: {e}"

        m = self._FAST_RISK_RE.search(raw)
        if m:
            return m.group(1).lower(), raw

        # Fallback: keyword scan
        lower = raw.lower()
        for level in ("critical", "high", "medium", "low", "safe"):
            if re.search(rf"\b{level}\b", lower):
                return level, raw
        return "unknown", raw

    _KNOWN_PATTERNS = [
        "urgency", "impersonation", "phone_avoidance",
        "new_account", "secrecy", "phishing_link", "credential_request",
    ]

    @staticmethod
    def _infer_tool_calls(
        risk_level: str,
        patterns: list[str],
        channel: str = "sms",
        text: str = "",
        metadata: dict | None = None,
    ) -> list[dict]:
        """Rule-based tool inference used when the model doesn't emit tool_calls in JSON."""
        tools: list[dict] = []
        incident_type = (
            "voice_scam" if channel == "voice"
            else "email_scam" if channel == "email"
            else "text_scam"
        )

        if risk_level in ("medium", "high", "critical"):
            tools.append({
                "name": "create_incident_report",
                "parameters": {"channel": channel, "patterns_detected": patterns, "raw_content": ""},
            })
        if risk_level in ("high", "critical"):
            tools.append({
                "name": "notify_trusted_contact",
                "parameters": {
                    "contact_id": "primary_family",
                    "risk_summary": f"Scam risk detected: {', '.join(patterns) or 'suspicious content'}",
                    "incident_type": incident_type,
                },
            })
        if "impersonation" in patterns:
            tools.append({
                "name": "suggest_callback",
                "parameters": {"claimed_identity": "unknown", "saved_contact_number": "use saved contact"},
            })
            if channel == "voice":
                tools.append({
                    "name": "generate_secret_question",
                    "parameters": {"claimed_relationship": "unknown", "context_hints": []},
                })
        if "urgency" in patterns or "new_account" in patterns:
            tools.append({
                "name": "start_wait_timer",
                "parameters": {"duration_seconds": 120, "reason": "Urgent payment request detected"},
            })
            tools.append({
                "name": "block_payment_intent",
                "parameters": {"trigger_keywords": ["send", "transfer", "wire", "money"]},
            })

        # ── New tools ──────────────────────────────────────────────────────
        # block_phone_number: voice/sms scams (medium+)
        if risk_level in ("medium", "high", "critical") and channel in ("voice", "sms"):
            phone = (metadata or {}).get("from_number") or "+1 (555) 000-0000"
            tools.append({
                "name": "block_phone_number",
                "parameters": {
                    "phone_number": phone,
                    "reason": f"Detected: {', '.join(patterns) or 'suspicious content'}",
                    "incident_type": incident_type,
                },
            })
        # block_email_sender: email channel (medium+)
        if risk_level in ("medium", "high", "critical") and channel == "email":
            email = (metadata or {}).get("from_email") or "unknown@scam.example"
            domain = email.split("@")[-1] if "@" in email else None
            tools.append({
                "name": "block_email_sender",
                "parameters": {
                    "email_address": email,
                    "sender_domain": domain,
                    "reason": f"Detected: {', '.join(patterns) or 'phishing'}",
                },
            })
        # check_url_safety: when phishing_link pattern OR a URL is in text
        url = _extract_url(text)
        if "phishing_link" in patterns or url:
            tools.append({
                "name": "check_url_safety",
                "parameters": {"url": url or "suspicious-link.example", "detected_in": channel},
            })
        # show_official_contact: when impersonation of a known brand
        brand = _detect_impersonated_brand(text)
        if brand:
            tools.append({
                "name": "show_official_contact",
                "parameters": {"impersonated_brand": brand},
            })
        # verify_image_message: when image OCR text was provided
        if metadata and metadata.get("image_extracted_text"):
            tools.append({
                "name": "verify_image_message",
                "parameters": {
                    "extracted_text": metadata["image_extracted_text"],
                    "image_source": metadata.get("image_source", "mms_attachment"),
                },
            })
        # flag_red_phrases: any medium+ risk
        if risk_level in ("medium", "high", "critical"):
            phrases = _extract_red_phrases(text)
            if phrases:
                tools.append({
                    "name": "flag_red_phrases",
                    "parameters": {
                        "phrases": phrases,
                        "risk_categories": ["scam_indicator"] * len(phrases),
                    },
                })
        return tools

    # Match scripts the fine-tuned model occasionally hallucinates (Devanagari,
    # CJK, Cyrillic, Arabic, Hebrew, Thai). The demo is English-only — anything
    # outside ASCII/Latin-1 punctuation here is training noise, not signal.
    _HALLUCINATED_SCRIPT_RE = re.compile(
        r"[Ѐ-ӿ"   # Cyrillic
        r"Ԁ-ԯ"
        r"֐-׿"    # Hebrew
        r"؀-ۿ"    # Arabic
        r"܀-ݏ"
        r"ऀ-ॿ"    # Devanagari
        r"฀-๿"    # Thai
        r"぀-ヿ"    # Hiragana/Katakana
        r"㐀-䶿"    # CJK ext A
        r"一-鿿"    # CJK
        r"가-힯"    # Hangul
        r"]+"
    )

    @classmethod
    def _clean_user_message(cls, text: str | None) -> str:
        """Turn whatever the model produced into a clean, professional prose
        message the UI can render directly.

        Handles three failure modes seen from the fine-tuned model:
          1. Wrapped in a ```json ... ``` code fence
          2. Pure JSON object leaked (e.g. {"risk_level": ..., "reason": ...})
          3. Stray non-Latin characters from training noise
        """
        if not text:
            return ""
        s = str(text).strip()

        # 1. Strip ```json / ```javascript / ``` fences.
        fence = re.match(r"^```(?:json|javascript|js)?\s*(.*?)\s*```$", s, re.DOTALL)
        if fence:
            s = fence.group(1).strip()

        # 2. If what remains looks like a JSON object, unpack it into prose.
        # The fine-tuned model frequently emits malformed JSON (missing quotes,
        # mismatched brackets), so we try strict parse first, then a regex
        # fallback that pulls key-value pairs out of the wreckage.
        if s.lstrip().startswith("{"):
            obj: dict | None = None
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                obj = cls._lenient_json_extract(s)
            if isinstance(obj, dict) and obj:
                s = cls._dict_to_prose(obj)

        # 3. Remove hallucinated non-Latin characters / scripts.
        s = cls._HALLUCINATED_SCRIPT_RE.sub("", s)

        # 4. Collapse stray whitespace artefacts created by removal.
        s = re.sub(r"[ \t]+", " ", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        s = re.sub(r"^\s*[:,\-–—]\s*", "", s, flags=re.MULTILINE)
        s = s.strip()

        if len(s) > 1200:
            s = s[:1200].rsplit(" ", 1)[0] + "…"
        return s

    # Pulls "key": "value" string pairs and "key": [ "a", "b" ] string lists out
    # of malformed JSON. Anchors on the colon-quote separator, so a missing
    # trailing quote on one value doesn't poison the rest of the parse.
    _KV_STRING_RE = re.compile(
        r'"([^"\n]{1,80})"\s*:\s*"((?:[^"\\]|\\.)*?)"(?=\s*[,}\n])',
        re.DOTALL,
    )
    _KV_ARRAY_RE = re.compile(
        r'"([^"\n]{1,80})"\s*:\s*\[(.*?)\]',
        re.DOTALL,
    )
    _ARRAY_ITEM_RE = re.compile(r'"((?:[^"\\]|\\.)*?)"(?=\s*[,\]])', re.DOTALL)

    # Looser pass: captures `"key": "<anything>` and stops at the next key
    # marker `<newline> "<key>":` (with or without closing quote/comma) or the
    # final `}`. Salvages values whose closing quote the model forgot.
    _KV_LOOSE_RE = re.compile(
        r'"([^"\n]{1,80})"\s*:\s*"(.*?)(?=\n\s*"[^"\n]{1,80}"\s*:|\n\s*}|\Z)',
        re.DOTALL,
    )

    @classmethod
    def _lenient_json_extract(cls, s: str) -> dict:
        """Best-effort recovery of key/value pairs from broken model JSON."""
        out: dict = {}
        # Pass 1: strict key/value matches (well-formed pairs).
        for key, val in cls._KV_STRING_RE.findall(s):
            key = key.strip()
            if key and key not in out:
                out[key] = val.replace('\\"', '"').replace("\\n", "\n").strip()
        # Pass 2: arrays of strings.
        for key, body in cls._KV_ARRAY_RE.findall(s):
            key = key.strip()
            items = [
                m.replace('\\"', '"').replace("\\n", "\n").strip()
                for m in cls._ARRAY_ITEM_RE.findall(body)
            ]
            items = [x for x in items if x]
            if key and items and key not in out:
                out[key] = items
        # Pass 3: loose pairs (rescues values with missing closing quote).
        for key, val in cls._KV_LOOSE_RE.findall(s):
            key = key.strip()
            if key and key not in out:
                cleaned = val.replace('\\"', '"').replace("\\n", "\n").rstrip(' \t"\n,')
                if cleaned.strip():
                    out[key] = cleaned.strip()
        return out

    @classmethod
    def _dict_to_prose(cls, obj: dict) -> str:
        """Render a JSON object the model returned as readable prose."""
        # Primary explanation field — try common variants the model invents.
        explanation_keys = (
            "reason", "explanation", "advice", "message", "response",
            "user_message", "summary", "analysis", "description",
        )
        lines: list[str] = []
        for k in explanation_keys:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                lines.append(v.strip())
                break

        # Bullet-style fields — flatten any list of strings under a likely key.
        bullet_keys = (
            "dangers", "warnings", "patterns", "red_flags", "concerns",
            "indicators", "issues", "reasons",
        )
        bullets: list[str] = []
        # Also accept arbitrary keys whose value is a list of strings (covers
        # hallucinated keys like "खतरे" / "위험"); we strip non-Latin script
        # later anyway, so the value matters more than the key here.
        for k, v in obj.items():
            if k in explanation_keys:
                continue
            if isinstance(v, list) and all(isinstance(x, str) for x in v) and v:
                if k in bullet_keys or len(bullets) == 0:
                    bullets.extend(x.strip() for x in v if x.strip())
            elif isinstance(v, str) and v.strip() and k not in explanation_keys:
                # Single-string sibling keys like "action_required"
                if k in ("action_required", "recommendation", "next_step", "action"):
                    bullets.append(v.strip())
        if bullets:
            lines.append("\n".join(f"• {b}" for b in bullets))

        return "\n\n".join(lines) if lines else ""

    @staticmethod
    def _normalize_parsed(parsed: dict, raw_output: str, known_patterns: list[str]) -> dict:
        """Normalise any JSON schema the model produces into our expected schema."""
        # 1. Normalize risk_level to lowercase
        rl = str(parsed.get("risk_level", "")).lower().strip()
        if rl not in ("safe", "low", "medium", "high", "critical"):
            rl = "safe"

        # 2. Extract patterns.
        # If the key is present (even as []), trust the model's answer — it explicitly
        # decided no patterns were present. Only text-scan if key is completely absent.
        raw_patterns = parsed.get("patterns")
        if raw_patterns is not None:
            patterns = raw_patterns  # model made an explicit call; trust it
            text_scan_used = False
        else:
            lower = raw_output.lower()
            patterns = [
                p for p in known_patterns
                if p in lower or p.replace("_", " ") in lower
            ]
            text_scan_used = True

        # 3. Pattern-count guardrail: only upgrade risk if patterns came from text scan,
        #    not if the model explicitly listed them (to avoid guardrail vs. safe JSON fight).
        if text_scan_used:
            if rl in ("safe", "low") and len(patterns) >= 2:
                rl = "medium"
            if rl in ("safe", "low", "medium") and len(patterns) >= 3:
                rl = "high"

        # 4. user_message: try several field name variants the model might use.
        # If the model packed its prose into a "reason" / "explanation" / etc.
        # field alongside a sibling list of dangers, _clean_user_message will
        # unpack it into prose; if it nested a whole JSON blob, that's handled
        # too. Fall back to the raw output as a last resort.
        user_msg_raw = (
            parsed.get("user_message")
            or parsed.get("advice")
            or parsed.get("explanation")
            or parsed.get("message")
            or parsed.get("response")
            or parsed.get("reason")
            or ""
        )
        if not user_msg_raw:
            # Model didn't surface a prose field — render the whole object.
            try:
                user_msg_raw = ScamReasoningAgent._dict_to_prose(parsed)
            except Exception:
                user_msg_raw = ""
        user_msg = ScamReasoningAgent._clean_user_message(user_msg_raw)
        if not user_msg:
            user_msg = ScamReasoningAgent._clean_user_message(raw_output)[:1200]

        # 5. tool_calls: use model's field if present and non-empty
        tool_calls = parsed.get("tool_calls", [])

        return {
            "risk_level": rl,
            "patterns": patterns,
            "user_message": user_msg,
            "tool_calls": tool_calls,
        }

    def _extract_json(self, raw_output: str) -> dict:
        """Extract the final JSON block from the model's output (after CoT reasoning)."""
        # Try ```json ... ``` block first
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if "risk_level" in parsed:
                    return self._normalize_parsed(parsed, raw_output, self._KNOWN_PATTERNS)
            except json.JSONDecodeError:
                pass

        # Try any bare { ... } block that contains risk_level
        brace_match = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw_output, re.DOTALL)
        if brace_match:
            for candidate in reversed(brace_match):
                try:
                    parsed = json.loads(candidate)
                    if "risk_level" in parsed:
                        return self._normalize_parsed(parsed, raw_output, self._KNOWN_PATTERNS)
                except json.JSONDecodeError:
                    continue

        # Fallback: parse risk_level from plain-text keywords (same as evaluate.py)
        risk_level = "safe"
        lower = raw_output.lower()
        rl_match = re.search(
            r'"risk_level"\s*:\s*"(safe|low|medium|high|critical)"',
            raw_output, re.IGNORECASE,
        )
        if rl_match:
            risk_level = rl_match.group(1).lower()
        else:
            for level in ["critical", "high", "medium", "low"]:
                if re.search(rf"\b{level}\b", lower):
                    risk_level = level
                    break
            # Also detect scam-positive language when no explicit level word is found
            if risk_level == "safe":
                scam_phrases = [
                    r"\bscam\b", r"\bphishing\b", r"\bfraud\b",
                    r"\bimmediate warning\b", r"\bdo not send\b", r"\bhallmarks\b",
                    r"\bwarning\b.*money", r"\bsuspicious\b",
                ]
                if any(re.search(p, lower) for p in scam_phrases):
                    risk_level = "medium"

        # Extract pattern names mentioned in the output
        detected_patterns = [
            p for p in self._KNOWN_PATTERNS
            if p in lower or p.replace("_", " ") in lower or p.replace("_", "-") in lower
        ]

        # Apply pattern-count guardrail (same logic as _normalize_parsed)
        if risk_level in ("safe", "low") and len(detected_patterns) >= 2:
            risk_level = "medium"
        if risk_level in ("safe", "low", "medium") and len(detected_patterns) >= 3:
            risk_level = "high"

        # Use the raw model output as the user_message (clean up repetition,
        # strip JSON fences / non-Latin noise, trim length)
        deduped = re.sub(r"(\b\w+\b)(\s+\1){3,}", r"\1 …", raw_output).strip()
        user_message = self._clean_user_message(deduped) or deduped[:1200]

        # Infer tool_calls from risk_level + patterns since model didn't produce JSON
        inferred_tools = self._infer_tool_calls(risk_level, detected_patterns)

        return {
            "risk_level": risk_level,
            "patterns": detected_patterns,
            "user_message": user_message,
            "tool_calls": inferred_tools,
        }

    def _run_once(self, signals: SignalInput, similar_cases: list[dict], temperature: float) -> tuple[dict, str]:
        user_message = self._build_user_message(signals, similar_cases)
        raw = self._call_ollama(user_message, temperature=temperature)
        parsed = self._extract_json(raw)
        return parsed, raw

    def analyze(
        self,
        signals: SignalInput,
        use_self_consistency: bool = True,
        use_cascade: bool = True,
    ) -> AgentOutput:
        """
        Analyze signals and return structured output.

        Hybrid cascade (default):
            Stage 1 — Gemma 3 4B fast classifier returns risk_level only.
            Stage 2 — If "safe", short-circuit. Otherwise Gemma 4 produces the
                      plain-language reasoning, tool_calls, and user_message.
            This mirrors the eval finding (gemma3:4b is the stronger classifier;
            gemma4 is the stronger reasoner with native function calling).

        Set use_cascade=False to skip Stage 1 (e.g. for evaluation parity).
        """
        # ── Stage 1: fast classify with Gemma 3 ──────────────────────────
        if use_cascade:
            fast_risk, fast_raw = self._fast_classify(signals)
            if fast_risk == "safe":
                # Short-circuit: skip Gemma 4 entirely.
                return AgentOutput(
                    risk_level="safe",
                    patterns=[],
                    user_message="This message appears to be normal. No warning signs detected.",
                    tool_calls=[],
                    tool_results=[],
                    raw_reasoning=f"[fast-classifier safe verdict]\n{fast_raw}",
                )

        # ── Stage 2: deep reasoning + function calling with Gemma 4 ──────
        similar_cases: list[dict] = []
        if self.rag_retriever:
            query = signals.text or signals.transcript or ""
            similar_cases = self.rag_retriever.retrieve(query)

        if use_self_consistency:
            results = []
            raw_outputs = []
            for _ in range(3):
                parsed, raw = self._run_once(signals, similar_cases, temperature=0.3)
                results.append(parsed)
                raw_outputs.append(raw)

            # Majority vote on risk_level
            risk_levels = [r.get("risk_level", "low") for r in results]
            final_risk = Counter(risk_levels).most_common(1)[0][0]
            final_parsed = next(r for r in results if r.get("risk_level") == final_risk)
            final_raw = raw_outputs[results.index(final_parsed)]
        else:
            final_parsed, final_raw = self._run_once(signals, similar_cases, temperature=0.3)

        risk_level = final_parsed.get("risk_level", "low")
        patterns = final_parsed.get("patterns", [])
        tool_calls = final_parsed.get("tool_calls", [])

        # If the model returned risk >= medium but no tool_calls, infer them
        if not tool_calls and risk_level in ("medium", "high", "critical"):
            tool_calls = self._infer_tool_calls(
                risk_level,
                patterns,
                signals.channel,
                text=signals.text or signals.transcript or "",
                metadata=signals.metadata,
            )

        # Execute tool calls
        tool_results: list[dict] = []
        for tc in tool_calls:
            result: ToolResult = execute_tool_call(tc.get("name", ""), tc.get("parameters", {}))
            tool_results.append(result.model_dump())

        return AgentOutput(
            risk_level=risk_level,
            patterns=patterns,
            user_message=final_parsed.get("user_message", ""),
            tool_calls=tool_calls,
            tool_results=tool_results,
            raw_reasoning=final_raw,
        )
