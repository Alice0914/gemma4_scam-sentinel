"use client";

import type { AgentOutput, PhoneState, Scenario } from "../page";

// ── Demo scenarios ────────────────────────────────────────────────────────────

const DEMO_SCENARIOS: Scenario[] = [
  {
    label: "👴 Grandparent scam",
    text: "Grandma, it's me Tyler. I got into a car accident and I'm at the hospital. I need $1,500 for the surgery right now. Please don't call my old number, it's broken. Don't tell Mom, she'll panic. Send it to this new account.",
    channel: "voice",
  },
  {
    label: "💼 BEC wire fraud",
    text: "Hi, I'm in back-to-back meetings and can't talk. I need you to process an urgent wire transfer of $47,500 to a new vendor account today. Details: Bank of America, routing 026009593, account 4891023476. Do not discuss with other staff. Please confirm once done.",
    channel: "email",
  },
  {
    label: "📦 Package phishing",
    text: "USPS: Your package delivery was attempted. To reschedule delivery, confirm your address and pay a $3.50 redelivery fee at: usps-redelivery-confirm.com",
    channel: "sms",
  },
  {
    label: "🏦 Chase bank phish",
    text: "Chase Alert: Unusual activity detected on your account. Verify identity immediately to prevent suspension: chase-secure-verify.com/login. Reply STOP to opt out.",
    channel: "sms",
  },
  {
    label: "📷 Image smishing",
    text: "[Image attached] FedEx-track.xyz/parcel — Delivery failed. Open the attached image to confirm address and pay $2.99 customs fee within 24 hours.",
    channel: "sms",
    metadata: {
      image_extracted_text:
        "FedEx Notice: Your package #FX482109 could not be delivered due to incomplete address. Confirm details and pay $2.99 customs fee at FedEx-track.xyz/parcel within 24 hours or your package will be returned to sender.",
      image_source: "mms_attachment",
      from_number: "+1 (888) 555-0193",
    },
  },
  {
    label: "✅ Normal message",
    text: "Dad, can you send me $40 for groceries? I'll pay you back when I see you Sunday. My Venmo is @jake-miller22",
    channel: "sms",
  },
];

// ── Reasoning step parser ─────────────────────────────────────────────────────

const STEP_ICONS: Record<string, string> = {
  IDENTIFY: "🔍",
  ASSESS: "⚖️",
  EXPLAIN: "💬",
  "DECIDE TOOLS": "🔧",
  "ANSWER FOUR QUESTIONS": "💡",
};

function parseSteps(raw: string) {
  const clean = raw
    .replace(/```json[\s\S]*?```/g, "")
    .replace(/\{[\s\S]*?"risk_level"[\s\S]*?\}/g, "")
    .trim();

  const steps: Array<{ num: string; title: string; content: string }> = [];
  const re = /Step\s+(\d+)\s*[—\-]+\s*([^:\n]+):([\s\S]*?)(?=Step\s+\d+\s*[—\-]|$)/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(clean)) !== null) {
    const content = m[3].trim();
    if (content) steps.push({ num: m[1], title: m[2].trim().toUpperCase(), content });
  }
  return steps;
}

// ── Risk / pattern display ────────────────────────────────────────────────────

const RISK_STYLE = {
  safe:     "text-green-400 bg-green-400/10 border-green-400/30",
  low:      "text-yellow-400 bg-yellow-400/10 border-yellow-400/30",
  medium:   "text-orange-400 bg-orange-400/10 border-orange-400/30",
  high:     "text-red-400 bg-red-400/10 border-red-400/30",
  critical: "text-red-300 bg-red-500/20 border-red-500/50",
};

const PATTERN_LABELS: Record<string, string> = {
  urgency:            "⏰ Urgency",
  impersonation:      "🎭 Impersonation",
  phone_avoidance:    "📵 Avoids callback",
  new_account:        "🏦 New account",
  secrecy:            "🤫 Secrecy demand",
  phishing_link:      "🔗 Phishing link",
  credential_request: "🔑 Credential request",
};

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  text: string;
  setText: (t: string) => void;
  channel: string;
  setChannel: (c: string) => void;
  onAnalyze: () => void;
  onLoadScenario: (s: Scenario) => void;
  phoneState: PhoneState;
  result: AgentOutput | null;
  error: string | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function AnalysisPanel({
  text, setText, channel, setChannel,
  onAnalyze, onLoadScenario,
  phoneState, result, error,
}: Props) {
  const loading = phoneState === "analyzing";
  const steps = result ? parseSteps(result.raw_reasoning) : [];

  return (
    <div className="h-full flex flex-col text-white">
      {/* Header */}
      <div className="px-8 pt-7 pb-5 border-b border-gray-800/60 shrink-0">
        <div className="flex items-center gap-3 mb-1.5">
          <span className="text-2xl">🛡️</span>
          <h1 className="text-xl font-semibold">Scam Sentinel</h1>
        </div>
        <p className="text-gray-400 text-xs leading-relaxed">
          A multimodal scam risk assistant. Select a scenario to simulate a real message arriving on the phone — then hit Analyze to see Gemma&nbsp;4 reason through it live.
        </p>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-8 py-6 space-y-6">

        {/* Demo scenarios */}
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
            Try a scenario
          </p>
          <div className="grid grid-cols-2 gap-2">
            {DEMO_SCENARIOS.map((s) => (
              <button
                key={s.label}
                onClick={() => onLoadScenario(s)}
                className="text-xs px-3 py-2.5 rounded-xl bg-gray-800/50 border border-gray-700/50 text-gray-300 hover:border-gray-500 hover:text-white hover:bg-gray-800 transition-all text-left leading-snug"
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* Input */}
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
            Or paste your own
          </p>

          {/* Channel tabs */}
          <div className="flex gap-1 mb-3 bg-gray-800/40 p-1 rounded-xl">
            {[["sms", "💬 SMS"], ["email", "📧 Email"], ["voice", "📞 Voice"], ["chat", "💭 Chat"]].map(
              ([val, label]) => (
                <button
                  key={val}
                  onClick={() => setChannel(val)}
                  className={`flex-1 text-[11px] py-1.5 rounded-lg transition-all ${
                    channel === val
                      ? "bg-blue-600 text-white font-semibold shadow-lg shadow-blue-600/20"
                      : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {label}
                </button>
              )
            )}
          </div>

          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={
              channel === "voice"
                ? "Enter voice call transcript…"
                : "Paste message, email, or text…"
            }
            rows={5}
            className="w-full px-4 py-3 rounded-xl bg-gray-800/60 border border-gray-700/50 text-gray-100 placeholder-gray-500 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/60 focus:border-transparent transition-all"
          />

          <button
            onClick={onAnalyze}
            disabled={!text.trim() || loading}
            className="mt-3 w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold transition-all shadow-lg shadow-blue-600/20"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Analyzing with Gemma 4…
              </span>
            ) : (
              "Analyze →"
            )}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="p-3 bg-red-950/40 border border-red-800/50 rounded-xl">
            <p className="text-red-400 text-xs">⚠️ {error}</p>
            <p className="text-red-500/60 text-[10px] mt-1">
              Is the backend running?{" "}
              <code className="bg-red-950/60 px-1 rounded font-mono">
                uvicorn backend.main:app --reload
              </code>
            </p>
          </div>
        )}

        {/* Result: risk + patterns + chain-of-thought */}
        {result && (
          <div className="space-y-5">
            {/* Risk level + patterns */}
            <div>
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
                Verdict
              </p>
              <div
                className={`inline-flex items-center px-3 py-1.5 rounded-full border text-sm font-bold ${
                  RISK_STYLE[result.risk_level] ?? RISK_STYLE.low
                }`}
              >
                {result.risk_level.toUpperCase()}
              </div>
              {result.patterns.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-3">
                  {result.patterns.map((p) => (
                    <span
                      key={p}
                      className="text-[10px] px-2.5 py-1 bg-gray-800 border border-gray-700 rounded-full text-gray-300"
                    >
                      {PATTERN_LABELS[p] ?? p}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Chain of thought */}
            {steps.length > 0 && (
              <div>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3">
                  Gemma 4 — Chain of Thought
                </p>
                <div className="space-y-2.5">
                  {steps.map((step, i) => (
                    <div
                      key={i}
                      className="bg-gray-800/40 border border-gray-700/40 rounded-xl overflow-hidden"
                    >
                      <div className="px-4 py-2 flex items-center gap-2 border-b border-gray-700/30 bg-gray-800/50">
                        <span className="text-base">{STEP_ICONS[step.title] ?? "▸"}</span>
                        <p className="text-xs font-semibold text-gray-100">
                          Step {step.num} — {step.title}
                        </p>
                      </div>
                      <div className="px-4 py-2.5">
                        <p className="text-xs text-gray-400 leading-relaxed whitespace-pre-wrap">
                          {step.content}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Fallback: raw reasoning */}
            {steps.length === 0 && result.raw_reasoning && (
              <div>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-2">
                  Raw Reasoning
                </p>
                <pre className="text-[10px] text-gray-400 bg-gray-800/40 rounded-xl p-4 overflow-auto max-h-64 whitespace-pre-wrap leading-relaxed font-mono">
                  {result.raw_reasoning}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
