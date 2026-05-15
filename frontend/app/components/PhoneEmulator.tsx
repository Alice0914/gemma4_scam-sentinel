"use client";

import { useState, useEffect, useRef } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import type { AgentOutput, PhoneState } from "../page";

const BACKEND = "http://localhost:8000";

// ── Real-time clock ──────────────────────────────────────────────────────────

function useClock() {
  const [time, setTime] = useState(() => {
    const d = new Date();
    return `${d.getHours()}:${d.getMinutes().toString().padStart(2, "0")}`;
  });
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      setTime(`${d.getHours()}:${d.getMinutes().toString().padStart(2, "0")}`);
    };
    const id = setInterval(tick, 30_000);
    return () => clearInterval(id);
  }, []);
  return time;
}

// ── Vibration trigger on incoming message/call ───────────────────────────────

function useVibration(text: string, channel: string, phoneState: PhoneState) {
  const [vibrating, setVibrating] = useState(false);
  const prev = useRef({ text, channel });
  useEffect(() => {
    const changed =
      phoneState === "preview" &&
      text &&
      (prev.current.text !== text || prev.current.channel !== channel);
    if (changed) {
      setVibrating(true);
      const id = setTimeout(() => setVibrating(false), 550);
      prev.current = { text, channel };
      return () => clearTimeout(id);
    }
    prev.current = { text, channel };
  }, [text, channel, phoneState]);
  return vibrating;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

type TR = { tool_name: string; success: boolean; data: Record<string, unknown> };

function getTool(results: Record<string, unknown>[], name: string): TR | undefined {
  return results.find((r) => r["tool_name"] === name) as TR | undefined;
}

// ── Compact countdown timer (for phone screen) ────────────────────────────────

function PhoneTimer({ seconds }: { seconds: number }) {
  const [rem, setRem] = useState(seconds);
  const done = rem <= 0;
  useEffect(() => {
    if (done) return;
    const id = setInterval(() => setRem((r) => Math.max(0, r - 1)), 1000);
    return () => clearInterval(id);
  }, [done]);
  const m = Math.floor(rem / 60);
  const s = rem % 60;
  return (
    <div className="flex items-center gap-2 bg-orange-500/20 border border-orange-500/40 rounded-xl px-3 py-2">
      <span className="text-sm">⏱️</span>
      <p className="flex-1 text-orange-200 text-[10px]">Wait before acting</p>
      <span className="font-mono text-orange-300 text-sm font-bold">
        {done ? "✓" : `${m}:${s.toString().padStart(2, "0")}`}
      </span>
    </div>
  );
}

// ── Risk config ───────────────────────────────────────────────────────────────

const RISK = {
  safe:     { label: "Safe",        gradient: "from-green-600 to-green-700",  icon: "✅" },
  low:      { label: "Low Risk",    gradient: "from-yellow-500 to-yellow-600", icon: "⚠️" },
  medium:   { label: "Medium Risk", gradient: "from-orange-500 to-orange-600", icon: "🔶" },
  high:     { label: "High Risk",   gradient: "from-red-500 to-red-600",       icon: "🚨" },
  critical: { label: "Critical",    gradient: "from-red-600 to-red-800",       icon: "🚫" },
};

// ── Feedback section (Self-Improving Cascade entry point) ────────────────────

function FeedbackSection({
  result,
  text,
  channel,
}: {
  result: AgentOutput;
  text: string;
  channel: string;
}) {
  const [submitted, setSubmitted] = useState<"correct" | "false_alarm" | null>(null);
  const [sending, setSending] = useState(false);

  async function sendFeedback(verdict: "correct" | "false_alarm") {
    if (submitted || sending) return;
    setSending(true);
    try {
      await fetch(`${BACKEND}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_text: text,
          channel,
          predicted_risk: result.risk_level,
          predicted_patterns: result.patterns,
          tool_calls: result.tool_calls,
          user_verdict: verdict,
          user_message_excerpt: result.user_message?.slice(0, 200) ?? "",
        }),
      });
      setSubmitted(verdict);
    } catch {
      // Silent fail — feedback is best-effort, not blocking.
      setSubmitted(verdict);
    } finally {
      setSending(false);
    }
  }

  if (submitted) {
    return (
      <div className="mx-1 mt-2 rounded-2xl bg-emerald-950/70 border border-emerald-500/30 px-3 py-3 shadow-lg feedback-fade">
        <div className="flex items-center gap-2 justify-center">
          <span className="text-base">✨</span>
          <p className="text-emerald-200 text-[11px] font-medium">
            Thanks! Your feedback trains the next version.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-1 mt-2 rounded-2xl bg-gray-900/95 border border-gray-700 px-3 py-3 shadow-lg">
      <p className="text-gray-300 text-[10px] font-medium text-center mb-2.5">
        Was this analysis correct?
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={sending}
          onClick={() => sendFeedback("false_alarm")}
          className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl bg-red-950/60 hover:bg-red-900/60 border border-red-500/30 hover:border-red-400/60 transition-colors disabled:opacity-50"
        >
          <ThumbsDown className="w-4 h-4 text-red-300" strokeWidth={1.75} />
          <span className="text-red-200 text-[10px] font-medium">False alarm</span>
        </button>
        <button
          type="button"
          disabled={sending}
          onClick={() => sendFeedback("correct")}
          className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl bg-green-950/60 hover:bg-green-900/60 border border-green-500/30 hover:border-green-400/60 transition-colors disabled:opacity-50"
        >
          <ThumbsUp className="w-4 h-4 text-green-300" strokeWidth={1.75} />
          <span className="text-green-200 text-[10px] font-medium">Spot on</span>
        </button>
      </div>
    </div>
  );
}

// ── Full-screen blocking warning — sits ON TOP of the underlying app screen ──
// so that links / buttons in the SMS or email cannot be tapped while the warning
// is up. Always renders, regardless of risk_level. For "safe" results the
// theming softens to green so it does not feel alarming.

function FullScreenWarning({
  result,
  text,
  channel,
  onDismiss,
}: {
  result: AgentOutput;
  text: string;
  channel: string;
  onDismiss: () => void;
}) {
  const isSafe = result.risk_level === "safe";
  const cfg = RISK[result.risk_level] ?? RISK.low;

  return (
    <div className="absolute inset-0 z-40 flex flex-col bg-black/80 backdrop-blur-md result-rise">
      {/* Top banner — explicit "we are blocking this" header */}
      <div
        className={`shrink-0 px-3 py-2 flex items-center gap-2 border-b ${
          isSafe
            ? "bg-emerald-900/70 border-emerald-500/40"
            : "bg-red-950/85 border-red-500/50"
        }`}
      >
        <span className="text-base">{isSafe ? "🛡️" : "🚨"}</span>
        <div className="flex-1 min-w-0">
          <p className={`text-[10px] font-bold uppercase tracking-wider ${
            isSafe ? "text-emerald-200" : "text-red-200"
          }`}>
            {isSafe
              ? "Scam Sentinel — scanned, looks normal"
              : "Scam Sentinel is blocking this content"}
          </p>
          <p className={`text-[9px] ${isSafe ? "text-emerald-300/80" : "text-red-300/80"}`}>
            {isSafe
              ? "You can interact with the message below."
              : "Links and actions are disabled until you confirm."}
          </p>
        </div>
        <span className={`text-[8px] px-2 py-0.5 rounded-full font-semibold ${
          isSafe ? "bg-emerald-500/30 text-emerald-100" : "bg-red-500/30 text-red-100"
        }`}>
          {cfg.label.toUpperCase()}
        </span>
      </div>

      {/* Scrollable result card body */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        <PhoneResultOverlay result={result} text={text} channel={channel} />
      </div>

      {/* Dismiss bar (always present so demo can flow to next scenario) */}
      <div className="shrink-0 px-3 pt-2 pb-2 border-t border-white/10 bg-black/60">
        <button
          type="button"
          onClick={onDismiss}
          className={`w-full py-2 rounded-xl text-[11px] font-semibold transition-colors ${
            isSafe
              ? "bg-emerald-600/70 hover:bg-emerald-500/80 text-white"
              : "bg-gray-700/80 hover:bg-gray-600/80 text-gray-100 border border-white/10"
          }`}
        >
          {isSafe ? "Continue" : "I understand the risk — dismiss"}
        </button>
        {!isSafe && (
          <p className="text-[8px] text-gray-400 text-center mt-1.5">
            We recommend deleting the message instead.
          </p>
        )}
      </div>
    </div>
  );
}

// ── Scam result overlay (compact, lives INSIDE FullScreenWarning) ────────────

function PhoneResultOverlay({
  result,
  text,
  channel,
}: {
  result: AgentOutput;
  text: string;
  channel: string;
}) {
  const cfg = RISK[result.risk_level] ?? RISK.low;
  const timer       = getTool(result.tool_results, "start_wait_timer");
  const payment     = getTool(result.tool_results, "block_payment_intent");
  const secret      = getTool(result.tool_results, "generate_secret_question");
  const cb          = getTool(result.tool_results, "suggest_callback");
  const blockPhone  = getTool(result.tool_results, "block_phone_number");
  const blockEmail  = getTool(result.tool_results, "block_email_sender");
  const urlCheck    = getTool(result.tool_results, "check_url_safety");
  const imgVerify   = getTool(result.tool_results, "verify_image_message");
  const officialCt  = getTool(result.tool_results, "show_official_contact");
  const redPhrases  = getTool(result.tool_results, "flag_red_phrases");
  const notify      = getTool(result.tool_results, "notify_trusted_contact");

  return (
    <div className="mx-1 rounded-2xl bg-gray-900/95 border border-gray-700 overflow-hidden shadow-2xl result-rise">
      {/* Risk header */}
      <div className={`bg-gradient-to-r ${cfg.gradient} px-3 py-2.5 flex items-center gap-2`}>
        <span className="text-lg">{cfg.icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-white text-xs font-bold">Scam Sentinel</p>
          <p className="text-white/80 text-[10px]">{cfg.label}</p>
        </div>
        <span className="text-[8px] text-white/60 bg-white/20 px-2 py-0.5 rounded-full shrink-0">
          PROTECTED
        </span>
      </div>

      {/* Plain-language message */}
      <div className="px-3 py-2.5">
        <p className="text-gray-200 text-[10px] leading-relaxed line-clamp-3">
          {result.user_message}
        </p>
      </div>

      {/* Action cards */}
      <div className="px-3 pb-3 space-y-1.5">
        {/* URL warning (popup-style, top priority) */}
        {urlCheck && (
          <div className="rounded-xl border-2 border-red-400/60 bg-gradient-to-br from-red-950/80 to-red-900/60 p-2.5">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-base">⚠️</span>
              <p className="text-red-200 text-[10px] font-bold">Dangerous link blocked</p>
            </div>
            <p className="text-red-300 text-[9px] font-mono bg-black/30 px-2 py-1 rounded line-through truncate">
              {urlCheck.data["url"] as string}
            </p>
            <p className="text-red-200/80 text-[9px] mt-1">
              {urlCheck.data["ui_message"] as string}
            </p>
          </div>
        )}

        {/* Official contact card */}
        {officialCt && (
          <div className="rounded-xl bg-gradient-to-br from-emerald-950/70 to-emerald-900/40 border border-emerald-500/30 p-2.5">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-sm">✓</span>
              <p className="text-emerald-200 text-[10px] font-semibold">Real contact</p>
            </div>
            <p className="text-white text-[10px] font-bold">{officialCt.data["brand_name"] as string}</p>
            <p className="text-emerald-300 text-[10px] font-mono">📞 {officialCt.data["real_phone"] as string}</p>
            <p className="text-emerald-300 text-[10px] font-mono">🌐 {officialCt.data["real_website"] as string}</p>
          </div>
        )}

        {/* Payment block */}
        {payment && (
          <div className="flex items-center gap-2 bg-red-950/70 border border-red-500/30 rounded-xl px-3 py-1.5">
            <span className="text-sm">🚫</span>
            <p className="text-red-300 text-[10px] font-medium">Payment blocked</p>
          </div>
        )}

        {/* Wait timer */}
        {timer && (
          <PhoneTimer seconds={(timer.data["duration_seconds"] as number) ?? 120} />
        )}

        {/* Secret question */}
        {secret && (
          <div className="bg-purple-950/70 border border-purple-500/30 rounded-xl px-3 py-1.5">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="text-sm">❓</span>
              <p className="text-purple-300 text-[10px] font-medium">Ask to verify identity:</p>
            </div>
            <p className="text-purple-200 text-[10px] italic pl-6 line-clamp-2">
              &ldquo;{secret.data["verification_question"] as string}&rdquo;
            </p>
          </div>
        )}

        {/* Callback */}
        {cb && (
          <div className="flex items-center gap-2 bg-blue-950/70 border border-blue-500/30 rounded-xl px-3 py-1.5">
            <span className="text-sm">📞</span>
            <p className="text-blue-300 text-[10px]">Call on saved number, not this one</p>
          </div>
        )}

        {/* Block phone number */}
        {blockPhone && (
          <div className="flex items-center gap-2 bg-slate-800/70 border border-slate-500/30 rounded-xl px-3 py-1.5">
            <span className="text-sm">📵</span>
            <div className="flex-1 min-w-0">
              <p className="text-slate-300 text-[10px] font-medium">Number blocked &amp; reported</p>
              <p className="text-slate-400 text-[9px] font-mono truncate">
                {blockPhone.data["phone_number"] as string} · {blockPhone.data["report_id"] as string}
              </p>
            </div>
          </div>
        )}

        {/* Block email sender */}
        {blockEmail && (
          <div className="flex items-center gap-2 bg-slate-800/70 border border-slate-500/30 rounded-xl px-3 py-1.5">
            <span className="text-sm">🚯</span>
            <div className="flex-1 min-w-0">
              <p className="text-slate-300 text-[10px] font-medium">Sender filtered</p>
              <p className="text-slate-400 text-[9px] font-mono truncate">
                {blockEmail.data["email_address"] as string}
              </p>
            </div>
          </div>
        )}

        {/* Image verification */}
        {imgVerify && (
          <div className="rounded-xl bg-amber-950/60 border border-amber-500/30 px-3 py-2">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-sm">🖼️</span>
              <p className="text-amber-200 text-[10px] font-semibold">
                Image OCR ({Math.round((imgVerify.data["ocr_confidence"] as number) * 100)}%)
              </p>
            </div>
            <p className="text-amber-100/80 text-[9px] italic line-clamp-2">
              &ldquo;{(imgVerify.data["extracted_text"] as string).slice(0, 80)}…&rdquo;
            </p>
          </div>
        )}

        {/* Red phrases */}
        {redPhrases && (
          <div className="rounded-xl bg-rose-950/60 border border-rose-500/30 px-3 py-2">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-sm">🔴</span>
              <p className="text-rose-200 text-[10px] font-semibold">Red-flag phrases</p>
            </div>
            <div className="flex flex-wrap gap-1">
              {((redPhrases.data["flagged_phrases"] as string[]) || []).slice(0, 4).map((p, i) => (
                <span key={i} className="text-[9px] px-1.5 py-0.5 bg-rose-900/60 text-rose-200 rounded font-mono">
                  {p}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Notify family */}
        {notify && (
          <div className="flex items-center gap-2 bg-green-950/60 border border-green-500/30 rounded-xl px-3 py-1.5">
            <span className="text-sm">👨‍👩‍👧</span>
            <p className="text-green-300 text-[10px]">Family notified</p>
          </div>
        )}
      </div>

      {/* Feedback (Self-Improving Cascade) */}
      <div className="px-2 pb-2">
        <FeedbackSection result={result} text={text} channel={channel} />
      </div>
    </div>
  );
}

// ── Dynamic Island ────────────────────────────────────────────────────────────

function DynamicIsland({ analyzing }: { analyzing: boolean }) {
  return (
    <div
      className={`absolute top-3 left-1/2 -translate-x-1/2 z-20 bg-black rounded-full flex items-center justify-center overflow-hidden transition-all duration-500 ${
        analyzing ? "w-36 h-8" : "w-28 h-7"
      }`}
    >
      {analyzing && (
        <div className="flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
          <span className="text-[9px] text-blue-300 font-medium">Analyzing…</span>
          <div
            className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse"
            style={{ animationDelay: "0.4s" }}
          />
        </div>
      )}
    </div>
  );
}

// ── Status bar ────────────────────────────────────────────────────────────────

function StatusBar() {
  const time = useClock();
  return (
    <div className="flex items-end justify-between px-7 pb-1.5 pt-1.5 text-white">
      <span className="text-[11px] font-semibold">{time}</span>
      <div className="flex items-center gap-1.5">
        {/* Signal bars */}
        <div className="flex gap-[2px] items-end h-3">
          {[4, 6, 8, 10].map((h, i) => (
            <div
              key={i}
              className={`w-[3px] rounded-[1px] ${i >= 1 ? "bg-white" : "bg-white/30"}`}
              style={{ height: `${h}px` }}
            />
          ))}
        </div>
        {/* WiFi */}
        <svg width="14" height="11" viewBox="0 0 14 11" fill="none">
          <path d="M7 8.5a1 1 0 1 1 0 2 1 1 0 0 1 0-2z" fill="white" />
          <path d="M4.17 6.33a4 4 0 0 1 5.66 0" stroke="white" strokeWidth="1.2" strokeLinecap="round" opacity="0.6" />
          <path d="M1.76 3.92a7.5 7.5 0 0 1 10.48 0" stroke="white" strokeWidth="1.2" strokeLinecap="round" opacity="0.3" />
        </svg>
        {/* Battery */}
        <div className="flex items-center gap-[1px]">
          <div className="w-[22px] h-[11px] border border-white/60 rounded-[2px] flex items-center px-[1.5px]">
            <div className="h-[7px] bg-white rounded-[1px]" style={{ width: "75%" }} />
          </div>
          <div className="w-[2px] h-[5px] bg-white/60 rounded-r-[1px]" />
        </div>
      </div>
    </div>
  );
}

// ── Notification banner (iOS-style) ──────────────────────────────────────────

function NotificationBanner({
  channel,
  text,
  visible,
}: {
  channel: string;
  text: string;
  visible: boolean;
}) {
  const [render, setRender] = useState(visible);
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    if (visible) {
      setRender(true);
      setExiting(false);
    } else if (render) {
      setExiting(true);
      const id = setTimeout(() => setRender(false), 320);
      return () => clearTimeout(id);
    }
  }, [visible, render]);

  if (!render) return null;

  const cfg =
    channel === "email"
      ? { icon: "✉️", iconBg: "bg-blue-500", app: "Mail", from: "CEO", preview: text }
      : channel === "voice"
      ? { icon: "📞", iconBg: "bg-green-500", app: "Phone", from: "Unknown Caller", preview: "Incoming call…" }
      : { icon: "💬", iconBg: "bg-green-500", app: "Messages", from: "Unknown", preview: text };

  return (
    <div
      className={`absolute top-12 left-2 right-2 z-30 ${exiting ? "notif-slide-out" : "notif-slide-in"}`}
    >
      <div className="rounded-2xl bg-gray-900/85 backdrop-blur-xl border border-white/10 px-2.5 py-2 flex gap-2 items-center shadow-2xl">
        <div className={`w-8 h-8 rounded-lg ${cfg.iconBg} flex items-center justify-center shrink-0 shadow`}>
          <span className="text-base">{cfg.icon}</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-0.5">
            <p className="text-white text-[10px] font-semibold uppercase tracking-wide">{cfg.app}</p>
            <p className="text-white/50 text-[9px]">now</p>
          </div>
          <p className="text-white text-[11px] font-medium leading-tight truncate">{cfg.from}</p>
          <p className="text-white/70 text-[10px] leading-tight line-clamp-1">{cfg.preview}</p>
        </div>
      </div>
    </div>
  );
}

// ── Idle / lock screen ────────────────────────────────────────────────────────

function IdleScreen() {
  return (
    <div className="h-full flex flex-col items-center bg-gradient-to-b from-blue-950 via-indigo-950 to-gray-950">
      <div className="flex-1 flex flex-col items-center justify-center gap-4">
        <div className="text-6xl drop-shadow-lg">🛡️</div>
        <div className="text-center">
          <p className="text-white text-xl font-light tracking-widest">Scam Sentinel</p>
          <p className="text-blue-300/70 text-xs mt-1">Your device is protected</p>
        </div>
        <div className="mt-6 flex flex-col items-center gap-1">
          <div className="w-8 h-1 bg-white/20 rounded-full" />
        </div>
      </div>
      <p className="mb-8 text-gray-500 text-[10px]">Select a scenario on the right →</p>
    </div>
  );
}

// ── SMS screen ────────────────────────────────────────────────────────────────

function SmsScreen({
  text,
  phoneState,
}: {
  text: string;
  phoneState: PhoneState;
}) {
  return (
    <div className="h-full flex flex-col bg-black">
      {/* Chat header */}
      <div className="px-4 py-2.5 flex items-center gap-3 bg-gray-900/80 border-b border-gray-800/60">
        <button className="text-blue-400 text-lg leading-none">‹</button>
        <div className="flex-1 flex flex-col items-center -ml-4">
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center mb-0.5 shadow-md ring-1 ring-white/10"
            style={{
              background:
                "linear-gradient(135deg, #fbbf24 0%, #f97316 50%, #dc2626 100%)",
            }}
          >
            <span className="text-white text-[11px] font-semibold drop-shadow">?</span>
          </div>
          <p className="text-white text-[11px] font-semibold leading-none">Unknown</p>
          <p className="text-gray-400 text-[9px]">+1 (555) 000-0000</p>
        </div>
        <button className="text-blue-400 text-sm">ⓘ</button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {text && (
          <div className="flex">
            <div className="max-w-[85%] bg-gray-700 rounded-2xl rounded-tl-sm px-3 py-2 shadow">
              <p className="text-white text-[11px] leading-relaxed">{text}</p>
              <p className="text-gray-400 text-[9px] mt-1">now</p>
            </div>
          </div>
        )}

        {phoneState === "analyzing" && (
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-blue-600 flex items-center justify-center text-[10px] shrink-0">
              🛡️
            </div>
            <div className="bg-gray-800 rounded-2xl rounded-tl-sm px-3 py-2 flex gap-1 items-center">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce"
                  style={{ animationDelay: `${i * 0.2}s` }}
                />
              ))}
            </div>
          </div>
        )}
        {/* Result is rendered as a full-screen blocking overlay at the
            PhoneEmulator level — no inline reply bubble. */}
      </div>

      {/* Input bar */}
      <div className="px-3 py-2 border-t border-gray-800/60 flex gap-2 items-center bg-gray-900/50">
        <button className="text-blue-400 text-xl leading-none">+</button>
        <div className="flex-1 bg-gray-800 rounded-full px-4 py-1.5">
          <span className="text-gray-500 text-[11px]">iMessage</span>
        </div>
        <button className="text-blue-400 text-xl">🎤</button>
      </div>
    </div>
  );
}

// ── Email screen ──────────────────────────────────────────────────────────────

function EmailScreen({
  text,
  phoneState,
}: {
  text: string;
  phoneState: PhoneState;
}) {
  return (
    <div className="h-full flex flex-col bg-white">
      <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-blue-500 text-sm font-medium">‹ Inbox</span>
          <div className="flex gap-3 text-blue-500 text-sm">
            <span>🗑️</span>
            <span>↩️</span>
            <span>⋯</span>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <div className="w-8 h-8 rounded-full bg-red-500 flex items-center justify-center text-white text-[9px] font-bold shrink-0 mt-0.5">
            CE
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline justify-between">
              <p className="text-gray-900 text-xs font-semibold">CEO</p>
              <p className="text-gray-400 text-[9px]">now</p>
            </div>
            <p className="text-gray-500 text-[9px] truncate">ceo@company-corp.net</p>
            <p className="text-gray-700 text-[10px] font-medium mt-0.5 truncate">
              URGENT: Wire Transfer Required
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {text && <p className="text-gray-800 text-[11px] leading-relaxed">{text}</p>}

        {phoneState === "analyzing" && (
          <div className="flex items-center gap-2 p-2.5 bg-blue-50 rounded-xl border border-blue-100">
            <span className="text-base">🛡️</span>
            <div>
              <p className="text-blue-700 text-[10px] font-medium">Scam Sentinel analyzing…</p>
              <div className="flex gap-1 mt-1">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 0.2}s` }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
        {/* Result is rendered as a full-screen blocking overlay at the
            PhoneEmulator level — no inline reply bubble. */}
      </div>
    </div>
  );
}

// ── Voice call screen ─────────────────────────────────────────────────────────

function CallScreen({
  phoneState,
}: {
  phoneState: PhoneState;
}) {
  const isAnalyzing = phoneState === "analyzing";
  const isResult = phoneState === "result";

  return (
    <div className="h-full flex flex-col bg-gradient-to-b from-gray-700 to-gray-950">
      {/* Caller info */}
      <div className="flex flex-col items-center pt-8 pb-4">
        <div className="relative mb-3">
          {!isAnalyzing && !isResult && (
            <div className="absolute inset-0 rounded-full ring-pulse" />
          )}
          <div className="relative w-20 h-20 rounded-full bg-gradient-to-br from-gray-400 to-gray-600 flex items-center justify-center shadow-xl">
            <span className="text-4xl">👤</span>
          </div>
        </div>
        <h2 className="text-white text-xl font-light">Unknown Caller</h2>
        <p className="text-gray-400 text-xs mt-1">+1 (555) 000-0000</p>
        {!isAnalyzing && !isResult && (
          <div className="flex items-center gap-1.5 mt-2">
            <p className="text-green-400 text-xs animate-pulse font-medium">Incoming Call…</p>
            <div className="flex items-end gap-[2px] h-3">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="w-[2px] bg-green-400 rounded-full"
                  style={{
                    animation: `sound-wave 0.9s ${i * 0.12}s ease-in-out infinite`,
                    height: "4px",
                  }}
                />
              ))}
            </div>
          </div>
        )}
        {isAnalyzing && (
          <div className="flex items-center gap-1.5 mt-2">
            <span className="text-xs">🛡️</span>
            <p className="text-blue-400 text-xs animate-pulse">Scam Sentinel analyzing…</p>
          </div>
        )}
      </div>

      {/* Analyzing indicator (result itself renders as a full-screen overlay at the parent level) */}
      <div className="flex-1 overflow-y-auto px-3">
        {isAnalyzing && (
          <div className="bg-black/40 rounded-xl p-3 border border-white/10 mx-1">
            <div className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce"
                  style={{ animationDelay: `${i * 0.2}s` }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Call controls */}
      {!isResult && (
        <div className="px-8 pb-8">
          {!isAnalyzing && (
            <div className="grid grid-cols-4 gap-3 mb-6">
              {[["🔇", "Mute"], ["⌨️", "Keypad"], ["📢", "Speaker"], ["➕", "Add"]].map(
                ([icon, label]) => (
                  <div key={label} className="flex flex-col items-center gap-1">
                    <div className="w-11 h-11 rounded-full bg-gray-700/80 flex items-center justify-center">
                      <span className="text-lg">{icon}</span>
                    </div>
                    <span className="text-gray-400 text-[9px]">{label}</span>
                  </div>
                )
              )}
            </div>
          )}
          <div className="flex justify-around">
            <div className="flex flex-col items-center gap-1.5">
              <button className="w-14 h-14 rounded-full bg-red-500 flex items-center justify-center shadow-lg shadow-red-500/30">
                <span className="text-xl">📵</span>
              </button>
              <span className="text-gray-400 text-[9px]">Decline</span>
            </div>
            {!isAnalyzing && (
              <div className="flex flex-col items-center gap-1.5">
                <button className="w-14 h-14 rounded-full bg-green-500 flex items-center justify-center shadow-lg shadow-green-500/30">
                  <span className="text-xl">📞</span>
                </button>
                <span className="text-gray-400 text-[9px]">Accept</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

interface Props {
  phoneState: PhoneState;
  text: string;
  channel: string;
  result: AgentOutput | null;
}

export default function PhoneEmulator({ phoneState, text, channel, result }: Props) {
  const analyzing = phoneState === "analyzing";
  const vibrating = useVibration(text, channel, phoneState);

  // Show notification banner briefly when a new message arrives.
  // Suppress for voice — incoming calls take over the full screen instead.
  const [bannerVisible, setBannerVisible] = useState(false);
  useEffect(() => {
    if (vibrating && channel !== "voice") {
      setBannerVisible(true);
      const id = setTimeout(() => setBannerVisible(false), 2600);
      return () => clearTimeout(id);
    }
  }, [vibrating, channel]);

  // Reset the dismissed flag whenever a new result arrives so the warning
  // overlay reappears for the next scenario.
  const [warningDismissed, setWarningDismissed] = useState(false);
  useEffect(() => {
    setWarningDismissed(false);
  }, [result]);
  const showWarning = phoneState === "result" && result !== null && !warningDismissed;

  function renderScreen() {
    if (phoneState === "idle") return <IdleScreen />;
    if (channel === "voice") return <CallScreen phoneState={phoneState} />;
    if (channel === "email") return <EmailScreen text={text} phoneState={phoneState} />;
    return <SmsScreen text={text} phoneState={phoneState} />;
  }

  return (
    <div className={`relative select-none ${vibrating ? "phone-shake" : ""}`}>
      {/* Phone shell */}
      <div
        className="relative w-[295px] h-[618px] rounded-[50px] bg-gradient-to-b from-gray-500 to-gray-700"
        style={{
          boxShadow: [
            "inset 0 0 0 1px rgba(255,255,255,0.14)",
            "inset 0 0 0 5px rgba(0,0,0,0.55)",
            "0 0 0 1px rgba(0,0,0,0.6)",
            "0 35px 90px rgba(0,0,0,0.85)",
            "0 0 60px rgba(59,130,246,0.06)",
          ].join(", "),
        }}
      >
        {/* Left buttons (silent switch + volume) */}
        <div className="absolute -left-[4px] top-[90px]  w-[4px] h-6  bg-gray-500 rounded-l-sm" />
        <div className="absolute -left-[4px] top-[130px] w-[4px] h-8  bg-gray-500 rounded-l-sm" />
        <div className="absolute -left-[4px] top-[173px] w-[4px] h-8  bg-gray-500 rounded-l-sm" />
        {/* Right button (power) */}
        <div className="absolute -right-[4px] top-[140px] w-[4px] h-16 bg-gray-500 rounded-r-sm" />

        {/* Screen */}
        <div className="absolute inset-[5px] rounded-[45px] overflow-hidden bg-black flex flex-col">
          {/* Dynamic Island */}
          <DynamicIsland analyzing={analyzing} />

          {/* Status bar */}
          <div className="relative z-10 shrink-0 pt-1">
            <StatusBar />
          </div>

          {/* Incoming notification banner (overlays current screen briefly) */}
          <NotificationBanner channel={channel} text={text} visible={bannerVisible} />

          {/* Screen content — full-screen warning sits ON TOP so URLs / buttons
              underneath cannot be tapped while a result is showing. */}
          <div className="flex-1 overflow-hidden relative">
            {renderScreen()}
            {showWarning && result && (
              <FullScreenWarning
                result={result}
                text={text}
                channel={channel}
                onDismiss={() => setWarningDismissed(true)}
              />
            )}
          </div>

          {/* Home indicator */}
          <div className="shrink-0 h-5 flex items-center justify-center">
            <div className="w-24 h-1 bg-white/20 rounded-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
