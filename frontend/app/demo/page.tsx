"use client";

import { useState, useEffect, useRef, useCallback } from "react";

type RiskLevel = "safe" | "low" | "medium" | "high" | "critical";

interface AgentOutput {
  risk_level: RiskLevel;
  patterns: string[];
  user_message: string;
  tool_calls: { name: string; parameters: Record<string, unknown> }[];
  tool_results: Record<string, unknown>[];
  raw_reasoning: string;
}

interface Segment {
  start: number;
  end: number;
  text: string;
}

interface VoiceFullResponse {
  transcript: string;
  segments: Segment[];
  duration: number;
  analysis: AgentOutput;
}

interface AnalysisCheck {
  atSecond: number;
  risk: RiskLevel;
  patterns: string[];
  toolCalls: { name: string; parameters: Record<string, unknown> }[];
  message: string;
}

const BACKEND = "http://localhost:8000";
const AUDIO_URL = "/demo_call.mp3";
const CALLER_NUMBER = "+1-555-0142";
const ANALYZE_INTERVAL_SEC = 20;

type CallState = "idle" | "connected" | "ended";

// ─────────────────────────────────────────────────────────────────────────────
// All demo scenarios, with the live phone call as the first option.
// Live call has its own dedicated UI; the others use the simpler text-channel
// analysis flow.
// ─────────────────────────────────────────────────────────────────────────────

type ScenarioKey =
  | "live_call"
  | "bec_email"
  | "chase_sms"
  | "image_smishing"
  | "normal_message";

interface TextScenario {
  key: ScenarioKey;
  label: string;
  emoji: string;
  channel: string;
  text: string;
  metadata?: Record<string, unknown>;
}

const SCENARIOS: { key: ScenarioKey; label: string; emoji: string }[] = [
  { key: "live_call", emoji: "📞", label: "Live phone call" },
  { key: "bec_email", emoji: "💼", label: "BEC wire fraud (email)" },
  { key: "chase_sms", emoji: "🏦", label: "Chase bank phish (SMS)" },
  { key: "image_smishing", emoji: "📷", label: "Image smishing (MMS)" },
  { key: "normal_message", emoji: "✅", label: "Normal family message (SMS)" },
];

const TEXT_SCENARIOS: Record<Exclude<ScenarioKey, "live_call">, TextScenario> = {
  bec_email: {
    key: "bec_email",
    label: "BEC wire fraud (email)",
    emoji: "💼",
    channel: "email",
    text:
      "Hi, I'm in back-to-back meetings and can't talk. I need you to process an urgent wire transfer of $47,500 to a new vendor account today. Details: Bank of America, routing 026009593, account 4891023476. Do not discuss with other staff. Please confirm once done.",
  },
  chase_sms: {
    key: "chase_sms",
    label: "Chase bank phish (SMS)",
    emoji: "🏦",
    channel: "sms",
    text:
      "Chase Alert: Unusual activity detected on your account. Verify identity immediately to prevent suspension: chase-secure-verify.com/login. Reply STOP to opt out.",
  },
  image_smishing: {
    key: "image_smishing",
    label: "Image smishing (MMS)",
    emoji: "📷",
    channel: "sms",
    text:
      "Hi, your FedEx package couldn't be delivered. Tap the image to confirm your address and pay the $2.99 customs fee before it gets returned.",
    metadata: {
      // Real PNG served from frontend/public/sample_mms/ — pytesseract reads
      // text out of THIS image at scan time (no hardcoded extracted text).
      image_url: "/sample_mms/fedex_scam.png",
      image_source: "mms_attachment",
      from_number: "+1 (888) 555-0193",
    },
  },
  normal_message: {
    key: "normal_message",
    label: "Normal family message (SMS)",
    emoji: "✅",
    channel: "sms",
    text:
      "Dad, can you send me $40 for groceries? I'll pay you back when I see you Sunday. My Venmo is @jake-miller22",
    metadata: {
      // Saved contact in the user's address book → emulator shows the name,
      // not the phone number, and skips the "unsaved number" warning banner.
      from_contact: "James (Son)",
      from_number: "+1 (415) 555-0136",
    },
  },
};

const RISK_COLORS: Record<RiskLevel, string> = {
  safe:     "bg-emerald-50 border-emerald-400 text-emerald-900",
  low:      "bg-yellow-50 border-yellow-400 text-yellow-900",
  medium:   "bg-orange-50 border-orange-400 text-orange-900",
  high:     "bg-red-50 border-red-500 text-red-900",
  critical: "bg-red-100 border-red-600 text-red-950",
};

function isDangerous(level: RiskLevel | null): boolean {
  return level === "medium" || level === "high" || level === "critical";
}

function riskEmoji(level: RiskLevel): string {
  if (level === "critical") return "🚨";
  if (level === "high") return "⚠️";
  if (level === "medium") return "🛑";
  if (level === "low") return "ℹ️";
  return "✅";
}

// Tools we intentionally suppress in the demo UI:
//   suggest_callback: a callback to a spoofed number can route back to the
//   scammer, so we never surface "call this back" as a recommendation.
const SUPPRESSED_TOOLS = new Set(["suggest_callback"]);

// iPhone-style status bar icons (signal · WiFi · battery). Rendered as inline
// SVG so they stay crisp at any zoom without an extra asset.
function StatusBarIcons() {
  return (
    <span className="flex items-center gap-1 text-gray-800">
      {/* Cellular signal — 4 bars */}
      <svg width="13" height="9" viewBox="0 0 13 9" fill="currentColor" aria-hidden="true">
        <rect x="0" y="6" width="2" height="3" rx="0.5" />
        <rect x="3" y="4" width="2" height="5" rx="0.5" />
        <rect x="6" y="2" width="2" height="7" rx="0.5" />
        <rect x="9" y="0" width="2" height="9" rx="0.5" />
      </svg>
      {/* WiFi — 3 arcs + dot */}
      <svg width="13" height="10" viewBox="0 0 16 12" fill="none" aria-hidden="true">
        <path d="M2 5 A8 8 0 0 1 14 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M4 7 A5 5 0 0 1 12 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M6 9 A2 2 0 0 1 10 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="8" cy="11" r="0.8" fill="currentColor" />
      </svg>
      {/* Battery — outline + ~80% fill + nub */}
      <svg width="22" height="10" viewBox="0 0 24 10" fill="none" aria-hidden="true">
        <rect x="0.5" y="0.5" width="20" height="9" rx="2" stroke="currentColor" strokeWidth="0.8" />
        <rect x="2" y="2" width="14" height="6" rx="1" fill="currentColor" />
        <rect x="21" y="3.5" width="1.5" height="3" rx="0.6" fill="currentColor" />
      </svg>
    </span>
  );
}

function toolLabel(name: string): string {
  // These are the tool calls Gemma 4 recommends — not actions that have
  // actually executed against real telephony / payment APIs. Labels use
  // imperative or "call" framing to stay honest with the user.
  const map: Record<string, string> = {
    notify_trusted_contact: "Alert a trusted family member",
    generate_secret_question: "Ask a secret-question to verify",
    start_wait_timer: "Wait 2 minutes before sending money",
    create_incident_report: "Log this incident",
    block_payment_intent: "Block the payment / transfer link",
    block_phone_number: "Block this caller's number",
    block_email_sender: "Block this email sender",
    check_url_safety: "Check the URL for phishing",
    verify_image_message: "Re-scan text inside the image",
    show_official_contact: "Use the official contact number",
    flag_red_phrases: "Quote the risky phrases used",
  };
  return map[name] ?? name;
}

function filterVisibleTools<T extends { name: string }>(tools: T[]): T[] {
  return tools.filter((t) => !SUPPRESSED_TOOLS.has(t.name));
}

// ─────────────────────────────────────────────────────────────────────────────
// Top-level demo page: scenario picker + chosen scenario's view
// ─────────────────────────────────────────────────────────────────────────────

export default function VoiceDemoPage() {
  const [selected, setSelected] = useState<ScenarioKey>("live_call");
  return (
    <div className="flex flex-col h-screen bg-white text-gray-900 overflow-hidden">
      <ScenarioTabs selected={selected} onSelect={setSelected} />
      <div className="flex-1 overflow-hidden">
        {selected === "live_call" ? (
          <LiveCallView />
        ) : (
          <TextScenarioView scenario={TEXT_SCENARIOS[selected]} />
        )}
      </div>
    </div>
  );
}

function ScenarioTabs({
  selected,
  onSelect,
}: {
  selected: ScenarioKey;
  onSelect: (k: ScenarioKey) => void;
}) {
  return (
    <div className="flex gap-1 px-4 py-2 border-b border-gray-200 bg-white overflow-x-auto">
      {SCENARIOS.map((s) => {
        const isActive = s.key === selected;
        return (
          <button
            key={s.key}
            onClick={() => onSelect(s.key)}
            className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition ${
              isActive
                ? "bg-emerald-600 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            {s.emoji} {s.label}
          </button>
        );
      })}
    </div>
  );
}

function LiveCallView() {
  const [callState, setCallState] = useState<CallState>("idle");
  const [segments, setSegments] = useState<Segment[]>([]);
  const [visibleCount, setVisibleCount] = useState(0);
  const [fullAnalysis, setFullAnalysis] = useState<AgentOutput | null>(null);
  const [checks, setChecks] = useState<AnalysisCheck[]>([]);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const analyzedSecondsRef = useRef<Set<number>>(new Set());
  const segmentsRef = useRef<Segment[]>([]);
  const fullAnalysisRef = useRef<AgentOutput | null>(null);

  useEffect(() => {
    segmentsRef.current = segments;
  }, [segments]);
  useEffect(() => {
    fullAnalysisRef.current = fullAnalysis;
  }, [fullAnalysis]);

  // ── Fetch segments + initial analysis on Ring ──────────────────────────────
  const fetchAndAnalyze = useCallback(async () => {
    setStatus("Whisper transcribing + Gemma 4 analyzing…");
    setError(null);
    try {
      const audioRes = await fetch(AUDIO_URL);
      if (!audioRes.ok) throw new Error(`Audio fetch failed: ${audioRes.status}`);
      const audioBlob = await audioRes.blob();

      const form = new FormData();
      form.append("audio", audioBlob, "demo_call.mp3");

      const res = await fetch(`${BACKEND}/analyze/voice_full`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Backend ${res.status}: ${txt.slice(0, 200)}`);
      }
      const data: VoiceFullResponse = await res.json();
      setSegments(data.segments);
      setFullAnalysis(data.analysis);
      setStatus(`Ready · ${data.segments.length} short phrases · ${data.duration.toFixed(1)}s`);
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("");
      return null;
    }
  }, []);

  // Keywords used to detect which patterns have been audibly spoken so far.
  // We only surface a pattern on the phone AFTER its trigger phrase has been
  // played, otherwise the notification feels clairvoyant.
  const PATTERN_KEYWORDS: Record<string, string[]> = {
    urgency: ["urgent", "right now", "immediately", "before it", "may go through", "hurry"],
    impersonation: [
      "fraud department",
      "this is the",
      "officer",
      "irs",
      "bank",
      "social security",
      "amazon",
      "your account",
    ],
    credential_request: [
      "code",
      "password",
      "verification",
      "social security number",
      "ssn",
      "pin",
      "read it back",
    ],
    phone_avoidance: [
      "don't hang up",
      "if you hang up",
      "stay on the line",
      "can't talk",
      "phone is broken",
      "don't call",
    ],
    secrecy: ["don't tell", "between us", "keep this", "don't mention", "confidential"],
    new_account: ["new account", "new bank", "different account", "this account number"],
    phishing_link: ["click", "http", ".com", ".xyz", ".net", "verify here", "link"],
  };

  // Tools that only make sense once specific patterns are heard. Used to
  // progressively unlock auto-actions as the call unfolds.
  const TOOL_TRIGGERS: Record<string, string[]> = {
    block_payment_intent: ["urgency"],
    start_wait_timer: ["urgency"],
    block_phone_number: ["impersonation"],
    block_email_sender: ["impersonation"],
    show_official_contact: ["impersonation"],
    flag_red_phrases: ["urgency", "credential_request"],
    notify_trusted_contact: ["urgency", "impersonation"],
    create_incident_report: [],
  };

  // ── Push an interval check using the cached full analysis ──────────────────
  // Only surface the patterns + tools whose trigger phrases have actually
  // been spoken by the audio at this point in the call.
  const pushIntervalCheck = useCallback((atSecond: number) => {
    const analysis = fullAnalysisRef.current;
    if (!analysis) return;

    const spokenSoFar = segmentsRef.current
      .filter((s) => s.end <= atSecond)
      .map((s) => s.text)
      .join(" ")
      .toLowerCase();

    const heardPatterns = analysis.patterns.filter((p) => {
      const kws = PATTERN_KEYWORDS[p] ?? [];
      // If we don't have keywords for this pattern, fall back to allowing it
      // once the call has been going for ~10s.
      if (kws.length === 0) return atSecond >= 10;
      return kws.some((kw) => spokenSoFar.includes(kw));
    });

    const allowedTools = analysis.tool_calls.filter((tc) => {
      const required = TOOL_TRIGGERS[tc.name];
      if (!required || required.length === 0) return true;
      return required.some((p) => heardPatterns.includes(p));
    });

    // Don't push an empty check — wait until at least one pattern is audible
    if (heardPatterns.length === 0) return;

    const escalatedRisk: RiskLevel =
      heardPatterns.length >= 3
        ? "critical"
        : heardPatterns.length >= 2
          ? analysis.risk_level
          : "medium";

    const check: AnalysisCheck = {
      atSecond,
      risk: escalatedRisk,
      patterns: heardPatterns,
      toolCalls: allowedTools,
      message: analysis.user_message,
    };
    setChecks((prev) => [...prev, check]);
  }, []);

  // ── Sync segment reveal + interval checks to playback ──────────────────────
  useEffect(() => {
    if (callState !== "connected") return;
    const audioEl = audioRef.current;
    if (!audioEl) return;

    function onTimeUpdate() {
      if (!audioEl) return;
      const t = audioEl.currentTime;

      // Reveal a segment only AFTER it has finished being spoken
      const count = segmentsRef.current.filter((s) => s.end <= t).length;
      setVisibleCount(count);

      // Fire a periodic check at each 20s mark (20s, 40s, 60s, …). The
      // ad-hoc DangerOverlay timestamp gate has been removed — checks are
      // strictly on the interval.
      const triggerSeconds: number[] = [];
      const fixedMark = Math.floor(t / ANALYZE_INTERVAL_SEC) * ANALYZE_INTERVAL_SEC;
      if (fixedMark > 0) triggerSeconds.push(fixedMark);

      for (const sec of triggerSeconds) {
        if (!analyzedSecondsRef.current.has(sec)) {
          analyzedSecondsRef.current.add(sec);
          pushIntervalCheck(sec);
        }
      }
    }

    audioEl.addEventListener("timeupdate", onTimeUpdate);
    return () => audioEl.removeEventListener("timeupdate", onTimeUpdate);
  }, [callState, pushIntervalCheck]);

  function startCall() {
    setSegments([]);
    setVisibleCount(0);
    setFullAnalysis(null);
    setChecks([]);
    setError(null);
    analyzedSecondsRef.current.clear();
    setCallState("connected");

    fetchAndAnalyze().then((data) => {
      if (data && audioRef.current) {
        audioRef.current.play().catch((e) =>
          setError(`Audio play failed: ${e instanceof Error ? e.message : String(e)}`)
        );
      }
    });
  }

  function endCall() {
    setCallState("ended");
    audioRef.current?.pause();
    if (audioRef.current) audioRef.current.currentTime = 0;
  }

  // Pause the audio without changing callState — used when the user taps
  // 🛑 HANG UP NOW so the audio (and therefore the transcript / interval
  // checks) stops the moment they decide to hang up, even while the
  // feedback panel is still on screen.
  function pauseAudio() {
    audioRef.current?.pause();
  }

  function reset() {
    setCallState("idle");
    setSegments([]);
    setVisibleCount(0);
    setFullAnalysis(null);
    setChecks([]);
    analyzedSecondsRef.current.clear();
  }

  const visibleSegments = segments.slice(0, visibleCount);

  // Auto-scroll the transcript column to the bottom whenever a new segment
  // becomes visible, so the latest line is always in view without the user
  // having to scroll manually.
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = transcriptScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visibleSegments.length]);
  // Surface the giant red overlay the moment any dangerous check arrives.
  // The check itself only fires on the 20-second interval, so the overlay
  // timing is paced by the interval — no separate timestamp gate.
  const dangerousCheck =
    [...checks].reverse().find((c) => isDangerous(c.risk)) ?? null;

  return (
    <main className="flex h-full bg-white text-gray-900 overflow-hidden">
      {/* Left: phone shell */}
      <div className="flex flex-col items-center justify-center w-[420px] shrink-0 border-r border-gray-200 relative">
        <PhoneShell
          callState={callState}
          callerNumber={CALLER_NUMBER}
          checks={checks}
          dangerousCheck={dangerousCheck}
          transcript={visibleSegments.map((s) => s.text).join(" ")}
          onStart={startCall}
          onPauseAudio={pauseAudio}
          onEnd={endCall}
          onReset={reset}
        />
        <audio ref={audioRef} src={AUDIO_URL} preload="auto" onEnded={endCall} />
      </div>

      {/* Right: live transcript + analysis history */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Live call analysis</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Whisper-base STT · fine-tuned Gemma 4 E2B · risk check every {ANALYZE_INTERVAL_SEC}s
            </p>
          </div>
          <div className="text-xs text-gray-500 text-right">
            {status && <div>{status}</div>}
            {segments.length > 0 && (
              <div>
                lines shown: {visibleCount}/{segments.length}
              </div>
            )}
          </div>
        </header>

        <div className="flex-1 flex overflow-hidden">
          {/* Left column — live transcript (Whisper) */}
          <div
            ref={transcriptScrollRef}
            className="flex-1 overflow-y-auto p-6 space-y-3 border-r border-gray-200"
          >
            <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">
              Live transcript
            </div>

            {error && (
              <div className="border border-red-400 bg-red-50 rounded-md p-3 text-sm text-red-800">
                {error}
              </div>
            )}

            {callState === "idle" && (
              <p className="text-sm text-gray-500">
                Click <span className="text-emerald-600">📞 Ring phone</span> on the
                left. Audio starts immediately. Each spoken phrase appears here
                after it has been said; Gemma 4 pushes a risk notification onto
                the phone screen every {ANALYZE_INTERVAL_SEC} seconds.
              </p>
            )}

            {visibleSegments.length === 0 && callState === "connected" && (
              <p className="text-sm text-gray-500 animate-pulse">Connecting…</p>
            )}

            {visibleSegments.map((s, i) => (
              <div
                key={i}
                className="border border-gray-200 rounded-md px-3 py-2 bg-gray-50 animate-in fade-in slide-in-from-bottom-2 duration-300 flex gap-3"
              >
                <div className="text-[10px] text-gray-500 mt-0.5 w-10 shrink-0">
                  {formatTime(s.end)}
                </div>
                <p className="text-sm text-gray-700 leading-relaxed flex-1">{s.text}</p>
              </div>
            ))}
          </div>

          {/* Right column — Gemma 4 risk checks history */}
          <div className="flex-1 overflow-y-auto p-6 space-y-2">
            <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">
              Gemma 4 risk checks {checks.length > 0 && `(${checks.length})`}
            </div>

            {checks.length === 0 && (
              <p className="text-sm text-gray-500">
                A check fires every {ANALYZE_INTERVAL_SEC} seconds while the
                call is live. Verdicts will appear here as they arrive.
              </p>
            )}

            {checks.map((c, i) => (
              <div
                key={i}
                className={`border rounded-md p-2.5 text-xs ${RISK_COLORS[c.risk]}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span>
                    @ {formatTime(c.atSecond)} — {c.patterns.join(", ") || "no patterns"}
                  </span>
                  <span className="font-semibold">
                    {riskEmoji(c.risk)} {c.risk.toUpperCase()}
                  </span>
                </div>
                {filterVisibleTools(c.toolCalls).length > 0 && (
                  <div className="opacity-90 mt-0.5">
                    Tools: {filterVisibleTools(c.toolCalls).map((t) => toolLabel(t.name)).join(" · ")}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Phone shell — iPhone-style call screen with prominent danger overlay
// ─────────────────────────────────────────────────────────────────────────────

function PhoneShell({
  callState,
  callerNumber,
  checks,
  dangerousCheck,
  transcript,
  onStart,
  onPauseAudio,
  onEnd,
  onReset,
}: {
  callState: CallState;
  callerNumber: string;
  checks: AnalysisCheck[];
  dangerousCheck: AnalysisCheck | null;
  transcript: string;
  onStart: () => void;
  onPauseAudio: () => void;
  onEnd: () => void;
  onReset: () => void;
}) {
  return (
    <div className="relative w-[300px] h-[620px] rounded-[44px] bg-white border-[10px] border-gray-900 shadow-2xl overflow-hidden">
      <div className="absolute top-0 left-0 right-0 h-7 px-6 flex items-center justify-between text-[10px] text-gray-800 z-20">
        <span>9:41</span>
        <StatusBarIcons />
      </div>
      <div className="absolute top-1.5 left-1/2 -translate-x-1/2 w-[90px] h-[26px] rounded-full bg-black z-30" />

      {callState === "idle" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-white p-6">
          <div className="text-center mb-8">
            <div className="text-xs text-gray-500 mb-1">Scam Sentinel demo</div>
            <div className="text-sm text-gray-700">
              One click starts an incoming call from an unsaved number.
            </div>
          </div>
          <button
            onClick={onStart}
            className="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-5 py-2.5 rounded-full transition"
          >
            📞 Ring phone
          </button>
        </div>
      )}

      {callState === "connected" && (
        <>
          {/* Base call screen */}
          <div className="absolute inset-0 flex flex-col bg-white px-4 pt-10 pb-6">
            <div className="w-full rounded-lg p-2 text-[10px] text-center mb-3 border bg-blue-50 border-blue-200 text-blue-800">
              🛡️ Scam Sentinel — scanning unknown number…
            </div>
            <div className="flex flex-col items-center mb-3">
              <div className="w-16 h-16 rounded-full bg-gray-200 flex items-center justify-center text-2xl mb-2">
                👤
              </div>
              <div className="text-xs text-gray-500">Unknown</div>
              <div className="text-sm text-gray-900 font-medium">{callerNumber}</div>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2 mb-3">
              {checks.length === 0 && (
                <div className="text-xl text-gray-900 text-center mt-6 animate-pulse font-semibold tracking-wide">
                  Listening…
                </div>
              )}
              {checks.map((c, i) => (
                <NotificationCard key={i} check={c} />
              ))}
            </div>
            <div className="flex justify-center">
              <button
                onClick={onEnd}
                className="w-14 h-14 rounded-full bg-red-600 hover:bg-red-500 flex items-center justify-center text-xl"
              >
                ✕
              </button>
            </div>
          </div>

          {/* DANGER overlay — kicks in the moment a dangerous check arrives */}
          {dangerousCheck && (
            <DangerOverlay
              check={dangerousCheck}
              callerNumber={callerNumber}
              transcript={transcript}
              onPauseAudio={onPauseAudio}
              onEnd={onEnd}
            />
          )}
        </>
      )}

      {callState === "ended" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-white p-6">
          <div className="text-sm text-gray-700 mb-1">Call ended</div>
          {checks.length > 0 && (
            <div className="text-xs text-gray-500 mb-4 text-center">
              {checks.length} risk check{checks.length === 1 ? "" : "s"} ·
              final: {checks[checks.length - 1].risk.toUpperCase()}
            </div>
          )}
          <button
            onClick={onReset}
            className="bg-gray-200 hover:bg-gray-300 text-gray-800 text-sm px-4 py-1.5 rounded-full"
          >
            Reset
          </button>
        </div>
      )}

      <div className="absolute bottom-1.5 left-1/2 -translate-x-1/2 w-24 h-1 rounded-full bg-gray-400 z-30" />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Big red overlay that takes over the phone when a dangerous check fires.
// Auto-pauses nothing — but the giant "HANG UP NOW" CTA dominates the screen.
// ─────────────────────────────────────────────────────────────────────────────

function DangerOverlay({
  check,
  callerNumber,
  transcript,
  onPauseAudio,
  onEnd,
}: {
  check: AnalysisCheck;
  callerNumber: string;
  transcript: string;
  onPauseAudio: () => void;
  onEnd: () => void;
}) {
  const critical = check.risk === "critical";
  const visibleTools = filterVisibleTools(check.toolCalls);
  const [showFeedback, setShowFeedback] = useState(false);

  if (showFeedback) {
    return (
      <FeedbackInline
        inputText={transcript}
        channel="voice"
        riskLevel={check.risk}
        patterns={check.patterns}
        toolCalls={check.toolCalls}
        userMessage={check.message ?? ""}
        tone="danger"
        onDone={onEnd}
      />
    );
  }

  return (
    <div className="absolute inset-0 z-40 backdrop-blur-md flex flex-col px-4 pt-10 pb-6 animate-in fade-in duration-200 bg-gradient-to-b from-red-950 via-red-950/95 to-black">
      {/* Fixed header */}
      <div className="text-center mb-3 shrink-0">
        <div className="text-[12px] uppercase tracking-widest mb-1 text-red-300">
          🛡️ Scam Sentinel
        </div>
        <div className="text-xl font-bold text-white">
          {critical ? "🚨 SCAM CALL" : "⚠️ Likely scam call"}
        </div>
        <div className="text-[13px] mt-1 text-red-200">
          <div>Risk: {check.risk.toUpperCase()}</div>
          <div>from {callerNumber}</div>
        </div>
      </div>

      {/* Scrollable middle */}
      <div className="flex-1 min-h-0 overflow-y-auto pr-1">
        {check.patterns.length > 0 && (
          <div className="rounded-lg p-3 mb-3 text-[14px] leading-relaxed bg-red-900/40 border border-red-500/40 text-red-100">
            <div className="font-semibold mb-1 text-white text-[15px]">Detected patterns</div>
            <ul className="space-y-1">
              {check.patterns.map((p, i) => (
                <li key={i}>• {p.replace(/_/g, " ")}</li>
              ))}
            </ul>
          </div>
        )}

        {visibleTools.length > 0 && (
          <div className="rounded-lg p-3 mb-3 text-[14px] leading-relaxed bg-red-900/30 border border-red-600/30 text-red-100">
            <div className="font-semibold mb-1 text-white text-[15px]">Protective steps to take</div>
            <ul className="space-y-1">
              {visibleTools.slice(0, 6).map((t, i) => (
                <li key={i}>▸ {toolLabel(t.name)}</li>
              ))}
            </ul>
          </div>
        )}

        {check.message && (
          <div className="bg-black/30 rounded-lg p-3 mb-3 text-[14px] text-gray-100 leading-relaxed whitespace-pre-wrap">
            {check.message}
          </div>
        )}
      </div>

      <div className="mt-auto flex flex-col gap-2">
        <button
          onClick={() => {
            onPauseAudio();
            setShowFeedback(true);
          }}
          className="bg-red-600 hover:bg-red-500 text-white text-sm font-bold py-3 px-2 rounded-full animate-pulse shadow-lg shadow-red-500/40 leading-tight"
        >
          🛑 HANG UP NOW &amp; BLOCK
          <br />
          <span className="text-[11px] font-mono opacity-90">{callerNumber}</span>
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Small notification card stacked behind the danger overlay
// ─────────────────────────────────────────────────────────────────────────────

function NotificationCard({ check }: { check: AnalysisCheck }) {
  const dangerous = isDangerous(check.risk);
  return (
    <div
      className={`rounded-md p-2 text-[10px] border animate-in fade-in slide-in-from-top-1 duration-300 ${
        dangerous
          ? "bg-red-100 border-red-500 text-red-900"
          : "bg-gray-100 border-gray-200 text-gray-700"
      }`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="font-medium">
          {riskEmoji(check.risk)} {check.risk.toUpperCase()}
        </span>
        <span className="opacity-60">@ {formatTime(check.atSecond)}</span>
      </div>
      {check.patterns.length > 0 && (
        <div className="opacity-80 mb-1">{check.patterns.join(", ")}</div>
      )}
      {filterVisibleTools(check.toolCalls).length > 0 && (
        <ul className="space-y-0.5">
          {filterVisibleTools(check.toolCalls).slice(0, 3).map((t, i) => (
            <li key={i} className="opacity-90">
              • {toolLabel(t.name)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Text-channel scenario view (SMS / Email / MMS)
// ─────────────────────────────────────────────────────────────────────────────

type TextPhase = "incoming" | "opening" | "preview" | "scanning" | "result" | "error";

function TextScenarioView({ scenario }: { scenario: TextScenario }) {
  const [phase, setPhase] = useState<TextPhase>("incoming");
  const [analysis, setAnalysis] = useState<AgentOutput | null>(null);
  const [error, setError] = useState<string | null>(null);
  // For image scenarios: "Not now" dismisses the Sentinel modal and reveals the
  // full chat thread + unblurred image so the user can see what they declined.
  const [modalDismissed, setModalDismissed] = useState(false);

  // Reset to incoming whenever the scenario changes
  useEffect(() => {
    setPhase("incoming");
    setAnalysis(null);
    setError(null);
    setModalDismissed(false);
  }, [scenario.key]);

  const imageUrl = scenario.metadata?.image_url
    ? String(scenario.metadata.image_url)
    : null;

  async function runTextScan() {
    setPhase("scanning");
    setAnalysis(null);
    setError(null);
    try {
      const res = await fetch(`${BACKEND}/analyze/text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: scenario.text,
          channel: scenario.channel,
          metadata: scenario.metadata,
        }),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Backend ${res.status}: ${txt.slice(0, 200)}`);
      }
      const data: AgentOutput = await res.json();
      setAnalysis(data);
      setPhase("result");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }

  async function openAndScan() {
    setAnalysis(null);
    setError(null);
    setPhase("opening");

    // Saved-contact messages: do NOT auto-scan. The user already trusts this
    // sender (it's in their address book), so we just open the message and
    // surface a manual "Scan with Sentinel" button for SIM-swap / hijacked-
    // account edge cases.
    if (isSavedContact) {
      return;
    }

    // Image MMS scenarios pause at a "preview" phase so the user can see the
    // image + caption text and explicitly tap "Scan this image" — which then
    // routes through the real /analyze/image endpoint (pytesseract OCR).
    // Pure text scenarios go straight from opening → scanning → /analyze/text.
    if (imageUrl) {
      setTimeout(() => setPhase("preview"), 500);
      return;
    }

    setTimeout(() => runTextScan(), 500);
  }

  async function scanImage() {
    if (!imageUrl) return;
    setPhase("scanning");
    setAnalysis(null);
    setError(null);
    try {
      const imgRes = await fetch(imageUrl);
      if (!imgRes.ok) throw new Error(`Could not load image: HTTP ${imgRes.status}`);
      const blob = await imgRes.blob();
      const filename = imageUrl.split("/").pop() || "mms_attachment.png";

      const formData = new FormData();
      formData.append("image", new File([blob], filename, { type: blob.type || "image/png" }));

      const res = await fetch(`${BACKEND}/analyze/image`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`Backend ${res.status}: ${txt.slice(0, 200)}`);
      }
      const data: AgentOutput = await res.json();
      setAnalysis(data);
      setPhase("result");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }

  function reset() {
    setPhase("incoming");
    setAnalysis(null);
    setError(null);
    setModalDismissed(false);
  }

  const channelIcon =
    scenario.channel === "email" ? "📧" : scenario.channel === "voice" ? "📞" : "💬";
  const channelLabel =
    scenario.channel === "email"
      ? "Email"
      : scenario.channel === "voice"
        ? "Voice"
        : "SMS";
  // If `from_contact` is set, the sender is saved in the user's address book —
  // the emulator should show the contact name (and skip the "unsaved number"
  // warning). Otherwise fall back to the raw number (unknown sender).
  const fromContact = scenario.metadata?.from_contact
    ? String(scenario.metadata.from_contact)
    : null;
  const senderLabel =
    scenario.channel === "email"
      ? "ceo@company-corp.net"
      : fromContact
        ? fromContact
        : scenario.metadata?.from_number
          ? String(scenario.metadata.from_number)
          : "+1 (555) 018-7421";
  const isSavedContact = !!fromContact;

  return (
    <main className="flex h-full bg-white text-gray-900 overflow-hidden">
      {/* Left: phone with full-screen takeover stages */}
      <div className="flex flex-col items-center justify-center w-[420px] shrink-0 border-r border-gray-200 p-6">
        <div className="relative w-[300px] h-[620px] rounded-[44px] bg-white border-[10px] border-gray-900 shadow-2xl overflow-hidden flex flex-col">
          <div className="absolute top-0 left-0 right-0 h-7 px-6 flex items-center justify-between text-[10px] text-gray-800 z-20">
            <span>9:41</span>
            <StatusBarIcons />
          </div>
          <div className="absolute top-1.5 left-1/2 -translate-x-1/2 w-[90px] h-[26px] rounded-full bg-black z-30" />

          {/* Phase 1 — Incoming notification (lock-screen-like) */}
          {phase === "incoming" && (
            <div className="absolute inset-0 flex flex-col bg-white px-4 pt-10 pb-6">
              <div className="mt-6 flex flex-col items-center text-gray-500 text-[11px] uppercase tracking-widest mb-2">
                Wednesday, May 14
              </div>
              <div className="text-center text-3xl text-gray-900 mb-6">9:41</div>

              {/* Notification banner */}
              <button
                onClick={openAndScan}
                className="w-full text-left bg-gray-100 rounded-2xl p-3 border border-gray-200 hover:border-emerald-400 transition mb-3 animate-in slide-in-from-top-2 duration-500"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] uppercase tracking-wider text-gray-500">
                    {channelIcon} {channelLabel}
                  </span>
                  <span className="text-[10px] text-gray-400">now</span>
                </div>
                <div className="text-[11px] font-semibold text-gray-900 mb-0.5">
                  {senderLabel}
                </div>
                <div className="text-[11px] text-gray-700 line-clamp-2">
                  {scenario.text.slice(0, 90)}…
                </div>
              </button>

              <div
                className={`mt-auto rounded-lg p-2 text-[10px] text-center border ${
                  isSavedContact
                    ? "bg-emerald-50 border-emerald-300 text-emerald-800"
                    : "bg-yellow-50 border-yellow-300 text-yellow-800"
                }`}
              >
                {isSavedContact
                  ? `🛡️ From a saved contact. Tap to open.`
                  : `🛡️ Sender not in your contacts. Tap to open.`}
              </div>
            </div>
          )}

          {/* Phase 2 — Opening message.
              For UNKNOWN senders, this is a brief flash before auto-scan kicks in.
              For SAVED CONTACTS, the auto-scan is intentionally skipped — the
              message just opens, and Sentinel only steps in if the user
              explicitly taps "Scan with Sentinel" (covers SIM-swap / hijacked
              family phone edge cases). */}
          {phase === "opening" && (
            <div className="absolute inset-0 flex flex-col bg-white px-4 pt-10 pb-6 animate-in fade-in duration-200">
              <div className="text-[10px] uppercase tracking-widest text-gray-500 mb-2 text-center">
                {channelIcon} {channelLabel} {isSavedContact ? "· saved contact" : "· from unknown"}
              </div>
              <div className="text-[11px] text-gray-500 mb-2 text-center">{senderLabel}</div>
              <div className="bg-gray-100 border border-gray-200 rounded-2xl p-3 mb-4 text-[12px] text-gray-900 leading-relaxed whitespace-pre-wrap">
                {scenario.text}
              </div>

              {isSavedContact && (
                <div className="mt-auto flex flex-col gap-2">
                  <div className="text-[10px] text-gray-500 text-center px-2 leading-snug">
                    Saved contacts aren&apos;t auto-scanned. Tap below only if
                    something feels off (e.g. SIM-swap or hijacked account).
                  </div>
                  <button
                    type="button"
                    onClick={runTextScan}
                    className="w-full py-2.5 rounded-full bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold"
                  >
                    🛡️ Scan with Sentinel
                  </button>
                  <button
                    type="button"
                    onClick={reset}
                    className="text-[11px] text-gray-500 hover:text-gray-800 underline"
                  >
                    Looks normal — close
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Phase 2b — iMessage-style chat thread (background) + center modal asking the user to scan.
              "Not now" dismisses the modal and reveals the full chat thread with the unblurred image. */}
          {phase === "preview" && imageUrl && (
            <>
              {/* Background: chat thread. When the modal is up the image is
                  blurred (Sentinel hides it for safety); when the user picks
                  "Not now" the blur drops so they can see the full message. */}
              <div className="absolute inset-0 flex flex-col bg-white animate-in fade-in duration-200">
                <div className="pt-9 px-3 pb-2 flex items-center border-b border-gray-200 bg-gray-50">
                  {modalDismissed && (
                    <button
                      type="button"
                      onClick={reset}
                      className="text-blue-600 text-[11px] hover:underline px-1"
                      aria-label="Back to inbox"
                    >
                      ← Inbox
                    </button>
                  )}
                  <div className="flex-1 flex flex-col items-center">
                    <div className="w-9 h-9 rounded-full bg-gray-300 flex items-center justify-center text-base mb-1">
                      👤
                    </div>
                    <div className="text-[10px] font-semibold text-gray-900">
                      {senderLabel}
                    </div>
                    <div className="text-[9px] text-gray-500">Not in your contacts</div>
                  </div>
                  {modalDismissed && <span className="w-10" /> /* spacer to keep header centered */}
                </div>
                <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
                  <div className="flex justify-start">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={imageUrl}
                      alt="MMS attachment"
                      className={`max-w-[230px] max-h-[300px] object-contain rounded-2xl border border-gray-200 bg-gray-100 ${
                        modalDismissed ? "" : "blur-md"
                      }`}
                    />
                  </div>
                  <div className="flex justify-start">
                    <div className="max-w-[80%] bg-gray-200 text-gray-900 rounded-2xl rounded-tl-md px-3 py-2 text-[12px] leading-snug whitespace-pre-wrap">
                      {scenario.text}
                    </div>
                  </div>
                  {modalDismissed && (
                    <div className="text-[9px] text-gray-400 text-center pt-1">
                      Delivered · now
                    </div>
                  )}
                </div>
                {modalDismissed && (
                  <div className="px-3 pb-4 pt-2 border-t border-gray-200 bg-gray-50 flex flex-col gap-2">
                    <button
                      type="button"
                      onClick={scanImage}
                      className="w-full py-2 rounded-full bg-emerald-600 hover:bg-emerald-500 text-white text-[12px] font-semibold"
                    >
                      🛡️ Scan with Scam Sentinel
                    </button>
                  </div>
                )}
              </div>

              {/* Center modal — only when not yet dismissed */}
              {!modalDismissed && (
                <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-in fade-in duration-200">
                  <div className="mx-4 w-[240px] bg-white rounded-2xl shadow-2xl p-3 text-center">
                    <div className="text-[10px] uppercase tracking-widest text-emerald-600 mb-2">
                      🛡️ Scam Sentinel
                    </div>

                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={imageUrl}
                      alt="MMS attachment preview"
                      className="w-full max-h-[180px] object-contain rounded-lg border border-gray-200 bg-gray-50 mb-2"
                    />

                    <div className="text-[12px] font-semibold text-gray-900 mb-1">
                      Image from an unsaved number
                    </div>
                    <div className="text-[10px] text-gray-600 leading-snug mb-3 px-1">
                      {senderLabel} isn't in your contacts. Scan this image for scam patterns before opening?
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setModalDismissed(true)}
                        className="flex-1 py-2 rounded-full bg-gray-100 hover:bg-gray-200 text-gray-700 text-[11px] font-medium"
                      >
                        Not now
                      </button>
                      <button
                        type="button"
                        onClick={scanImage}
                        className="flex-1 py-2 rounded-full bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-semibold"
                      >
                        OK, scan
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Phase 3 — Scanning takeover */}
          {phase === "scanning" && (
            <div className="absolute inset-0 z-40 bg-gradient-to-b from-blue-950 via-indigo-950 to-black backdrop-blur-md flex flex-col items-center justify-center px-5 py-10 animate-in fade-in duration-300">
              <div className="text-[10px] uppercase tracking-widest text-blue-300 mb-2">
                🛡️ Scam Sentinel
              </div>
              <div className="text-base font-bold text-white text-center leading-snug mb-1">
                {imageUrl
                  ? "MMS image from unknown"
                  : isSavedContact
                    ? `Manual scan — ${senderLabel}`
                    : `${channelLabel} from an unsaved sender`}
              </div>
              <div className="text-[11px] text-blue-200/90 text-center mb-8 px-2">
                {imageUrl ? (
                  <>
                    Running pytesseract OCR…
                    <br />
                    then fine-tuned Gemma 4 E2B.
                  </>
                ) : isSavedContact ? (
                  <>
                    You asked for a second opinion on a saved contact.
                    <br />
                    Running fine-tuned Gemma 4 E2B…
                  </>
                ) : (
                  <>
                    We need to check this before you act.
                    <br />
                    Running fine-tuned Gemma 4 E2B…
                  </>
                )}
              </div>

              {/* Animated scanning spinner */}
              <div className="relative w-16 h-16 mb-4">
                <div className="absolute inset-0 rounded-full border-2 border-blue-400/20" />
                <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-blue-300 animate-spin" />
              </div>
              <div className="text-[11px] text-blue-100 animate-pulse">processing…</div>

              <div className="mt-auto text-[10px] text-blue-300/70 text-center">
                12 protective tools
              </div>
            </div>
          )}

          {/* Phase 4 — Result takeover */}
          {phase === "result" && analysis && (
            <ResultTakeover
              analysis={analysis}
              channelLabel={channelLabel}
              senderLabel={senderLabel}
              inputText={scenario.text}
              channel={scenario.channel}
              onReset={reset}
            />
          )}

          {/* Phase 5 — Error */}
          {phase === "error" && (
            <div className="absolute inset-0 z-40 bg-black/95 backdrop-blur-md flex flex-col items-center justify-center px-5">
              <div className="text-sm text-red-300 mb-2">Analysis failed</div>
              <div className="text-[10px] text-red-400 text-center mb-4">{error}</div>
              <button
                onClick={reset}
                className="bg-gray-700 hover:bg-gray-600 text-white text-xs px-4 py-1.5 rounded-full"
              >
                Try again
              </button>
            </div>
          )}

          <div className="absolute bottom-1.5 left-1/2 -translate-x-1/2 w-24 h-1 rounded-full bg-white/40 z-30" />
        </div>
      </div>

      {/* Right: status panel */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">
              {scenario.emoji} {scenario.label}
            </h1>
            <p className="text-xs text-gray-500 mt-0.5">
              fine-tuned Gemma 4 E2B + QLoRA · /analyze/text
            </p>
          </div>
          <button
            onClick={reset}
            className="bg-gray-800 hover:bg-gray-700 text-white text-xs font-medium px-3 py-1.5 rounded-full transition"
          >
            Reset
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {phase === "incoming" && (
            <p className="text-sm text-gray-500">
              The phone just received a {channelLabel.toLowerCase()} from an
              unsaved sender. Tap the notification on the phone to open it —
              Scam Sentinel will full-screen-block any action until the
              fine-tuned Gemma 4 has scanned the content.
            </p>
          )}

          {phase === "opening" && (
            <p className="text-sm text-gray-500 animate-pulse">Opening message…</p>
          )}

          {phase === "scanning" && (
            <div className="border border-blue-400 bg-blue-50 rounded-md p-4 text-sm text-blue-900">
              <div className="font-semibold text-blue-950 mb-1">
                {isSavedContact
                  ? `🛡️ Manual second-opinion scan — ${senderLabel}`
                  : "🛡️ Scanning unsaved-sender content"}
              </div>
              <ul className="space-y-1 text-xs opacity-90">
                {isSavedContact ? (
                  <>
                    <li>• Saved contact — user-triggered scan only</li>
                    <li>
                      • Checking for SIM-swap / hijacked-account signals
                      (urgency, secrecy, payment requests)
                    </li>
                    <li>• Routing text + metadata to fine-tuned Gemma 4 E2B</li>
                  </>
                ) : (
                  <>
                    <li>• Sender not in contacts → mandatory scan</li>
                    <li>• Routing text + metadata to fine-tuned Gemma 4 E2B</li>
                    <li>• Phone is blocked from any action until verdict returns</li>
                  </>
                )}
              </ul>
            </div>
          )}

          {phase === "error" && error && (
            <div className="border border-red-400 bg-red-50 rounded-md p-3 text-sm text-red-800">
              {error}
            </div>
          )}

          {phase === "result" && analysis && (
            <>
              <div
                className={`border rounded-md p-4 ${RISK_COLORS[analysis.risk_level]}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs uppercase tracking-wider opacity-80">
                    Gemma 4 verdict
                  </span>
                  <span className="text-sm font-semibold">
                    {riskEmoji(analysis.risk_level)} {analysis.risk_level.toUpperCase()}
                  </span>
                </div>
                {analysis.patterns.length > 0 && (
                  <div className="text-xs mb-2">
                    Patterns: {analysis.patterns.join(", ")}
                  </div>
                )}
                <p className="text-sm whitespace-pre-wrap">
                  {analysis.user_message}
                </p>
              </div>

              {filterVisibleTools(analysis.tool_calls).length > 0 && (
                <div className="border border-gray-200 rounded-md p-4 bg-gray-50">
                  <div className="text-xs uppercase tracking-wider text-gray-500 mb-2">
                    Protective steps Gemma 4 called for ({filterVisibleTools(analysis.tool_calls).length})
                  </div>
                  <ul className="space-y-1 text-sm">
                    {filterVisibleTools(analysis.tool_calls).map((t, i) => (
                      <li key={i} className="flex items-baseline gap-2">
                        <span className="text-emerald-600">▸</span>
                        <span>{toolLabel(t.name)}</span>
                        <span className="text-xs text-gray-500 ml-auto">{t.name}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Full-screen result takeover for text scenarios — same shape regardless of
// risk level, color and CTA shift based on dangerous vs safe.
// ─────────────────────────────────────────────────────────────────────────────

// Inline feedback panel — Self-Improving Cascade entry point.
// Shows two buttons (False alarm / Spot on) → POST /feedback → thank-you →
// auto-dismiss after 2s by calling onDone.
function FeedbackInline({
  inputText,
  channel,
  riskLevel,
  patterns,
  toolCalls,
  userMessage,
  tone,
  onDone,
}: {
  inputText: string;
  channel: string;
  riskLevel: string;
  patterns: string[];
  toolCalls: { name: string; parameters: Record<string, unknown> }[];
  userMessage: string;
  tone: "danger" | "safe";
  onDone: () => void;
}) {
  const [submitted, setSubmitted] = useState<"correct" | "false_alarm" | null>(null);
  const [sending, setSending] = useState(false);

  async function send(verdict: "correct" | "false_alarm") {
    if (submitted || sending) return;
    setSending(true);
    try {
      await fetch(`${BACKEND}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_text: inputText,
          channel,
          predicted_risk: riskLevel,
          predicted_patterns: patterns,
          tool_calls: toolCalls,
          user_verdict: verdict,
          user_message_excerpt: userMessage.slice(0, 200),
        }),
      });
    } catch {
      // Best-effort; never block the demo on a feedback failure.
    } finally {
      setSubmitted(verdict);
      setSending(false);
      setTimeout(onDone, 2000);
    }
  }

  const panelBg =
    tone === "danger"
      ? "bg-gradient-to-b from-red-950 via-red-950/95 to-black"
      : "bg-gradient-to-b from-emerald-950 via-emerald-950/90 to-black";

  if (submitted) {
    return (
      <div className={`absolute inset-0 z-50 ${panelBg} backdrop-blur-md flex flex-col items-center justify-center px-6 animate-in fade-in duration-200`}>
        <div className="text-4xl mb-3">✨</div>
        <div className="text-white text-base font-semibold text-center mb-1">Thanks!</div>
        <div className="text-gray-200 text-[12px] text-center max-w-[220px] leading-relaxed">
          Your feedback trains the next version of the model.
        </div>
      </div>
    );
  }

  return (
    <div className={`absolute inset-0 z-50 ${panelBg} backdrop-blur-md flex flex-col items-center justify-center px-5 py-8 animate-in fade-in duration-200`}>
      <div className="text-[10px] uppercase tracking-widest text-gray-300 text-center mb-2">
        🛡️ Scam Sentinel
      </div>
      <div className="text-base font-bold text-white text-center mb-6">
        Was this analysis helpful?
      </div>

      <div className="flex flex-col gap-3 w-full">
        <button
          type="button"
          disabled={sending}
          onClick={() => send("correct")}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-full bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold transition disabled:opacity-50"
        >
          👍 Yes, helpful
        </button>
        <button
          type="button"
          disabled={sending}
          onClick={onDone}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-full bg-gray-700 hover:bg-gray-600 border border-gray-500 text-white text-sm font-semibold transition disabled:opacity-50"
        >
          🤷 Not sure
        </button>
        <button
          type="button"
          disabled={sending}
          onClick={() => send("false_alarm")}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-full bg-gray-800 hover:bg-gray-700 border border-gray-600 text-white text-sm font-semibold transition disabled:opacity-50"
        >
          👎 Not helpful
        </button>
      </div>
    </div>
  );
}

function ResultTakeover({
  analysis,
  channelLabel,
  senderLabel,
  inputText,
  channel,
  onReset,
}: {
  analysis: AgentOutput;
  channelLabel: string;
  senderLabel: string;
  inputText: string;
  channel: string;
  onReset: () => void;
}) {
  const dangerous = isDangerous(analysis.risk_level);
  const critical = analysis.risk_level === "critical";
  const visibleTools = filterVisibleTools(analysis.tool_calls);
  const [showFeedback, setShowFeedback] = useState(false);

  if (showFeedback) {
    return (
      <FeedbackInline
        inputText={inputText}
        channel={channel}
        riskLevel={analysis.risk_level}
        patterns={analysis.patterns}
        toolCalls={analysis.tool_calls}
        userMessage={analysis.user_message ?? ""}
        tone={dangerous ? "danger" : "safe"}
        onDone={onReset}
      />
    );
  }

  return (
    <div
      className={`absolute inset-0 z-40 backdrop-blur-md flex flex-col px-4 pt-10 pb-6 animate-in fade-in duration-200 ${
        dangerous
          ? "bg-gradient-to-b from-red-950 via-red-950/95 to-black"
          : "bg-gradient-to-b from-emerald-950 via-emerald-950/90 to-black"
      }`}
    >
      {/* Fixed header — always visible */}
      <div className="text-center mb-3 shrink-0">
        <div
          className={`text-[12px] uppercase tracking-widest mb-1 ${
            dangerous ? "text-red-300" : "text-emerald-300"
          }`}
        >
          🛡️ Scam Sentinel
        </div>
        <div className="text-xl font-bold text-white">
          {critical
            ? `🚨 SCAM ${channelLabel.toUpperCase()}`
            : dangerous
              ? `⚠️ Likely scam ${channelLabel.toLowerCase()}`
              : "✅ Looks normal"}
        </div>
        <div
          className={`text-[13px] mt-1 ${
            dangerous ? "text-red-200" : "text-emerald-200"
          }`}
        >
          <div>Risk: {analysis.risk_level.toUpperCase()}</div>
          <div>from {senderLabel}</div>
        </div>
      </div>

      {/* Scrollable middle — patterns + tools + plain-language explanation */}
      <div className="flex-1 min-h-0 overflow-y-auto pr-1">
        {analysis.patterns.length > 0 && (
          <div
            className={`rounded-lg p-3 mb-3 text-[14px] leading-relaxed ${
              dangerous
                ? "bg-red-900/40 border border-red-500/40 text-red-100"
                : "bg-emerald-900/30 border border-emerald-500/30 text-emerald-100"
            }`}
          >
            <div className="font-semibold mb-1 text-white text-[15px]">Detected patterns</div>
            <ul className="space-y-1">
              {analysis.patterns.map((p, i) => (
                <li key={i}>• {p.replace(/_/g, " ")}</li>
              ))}
            </ul>
          </div>
        )}

        {visibleTools.length > 0 && (
          <div
            className={`rounded-lg p-3 mb-3 text-[14px] leading-relaxed ${
              dangerous
                ? "bg-red-900/30 border border-red-600/30 text-red-100"
                : "bg-emerald-900/20 border border-emerald-600/30 text-emerald-100"
            }`}
          >
            <div className="font-semibold mb-1 text-white text-[15px]">
              {dangerous ? "Protective steps to take" : "No actions needed"}
            </div>
            {dangerous && (
              <ul className="space-y-1">
                {visibleTools.slice(0, 6).map((t, i) => (
                  <li key={i}>▸ {toolLabel(t.name)}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {analysis.user_message && (
          <div className="bg-black/30 rounded-lg p-3 mb-3 text-[14px] text-gray-100 leading-relaxed whitespace-pre-wrap">
            {analysis.user_message}
          </div>
        )}
      </div>

      <div className="mt-auto flex flex-col gap-2">
        {dangerous ? (
          <button
            onClick={() => setShowFeedback(true)}
            className="bg-red-600 hover:bg-red-500 text-white text-base font-bold py-3 rounded-full animate-pulse shadow-lg shadow-red-500/40"
          >
            🛑 DELETE & BLOCK SENDER
          </button>
        ) : (
          <button
            onClick={() => setShowFeedback(true)}
            className="bg-emerald-600 hover:bg-emerald-500 text-white text-base font-bold py-3 rounded-full"
          >
            Continue
          </button>
        )}
      </div>
    </div>
  );
}

