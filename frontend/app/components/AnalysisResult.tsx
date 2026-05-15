"use client";

import { useState, useEffect } from "react";
import type { AgentOutput } from "../page";

// ── Risk level display config ────────────────────────────────────────────────

const RISK_CONFIG = {
  safe: {
    label: "Safe",
    bg: "bg-green-50 dark:bg-green-900/20",
    border: "border-green-200 dark:border-green-800",
    badge: "bg-green-100 dark:bg-green-800 text-green-800 dark:text-green-100",
    icon: "✅",
    bar: "bg-green-500",
    width: "w-[5%]",
  },
  low: {
    label: "Low Risk",
    bg: "bg-yellow-50 dark:bg-yellow-900/20",
    border: "border-yellow-200 dark:border-yellow-800",
    badge: "bg-yellow-100 dark:bg-yellow-800 text-yellow-800 dark:text-yellow-100",
    icon: "⚠️",
    bar: "bg-yellow-400",
    width: "w-[25%]",
  },
  medium: {
    label: "Medium Risk",
    bg: "bg-orange-50 dark:bg-orange-900/20",
    border: "border-orange-200 dark:border-orange-800",
    badge: "bg-orange-100 dark:bg-orange-800 text-orange-800 dark:text-orange-100",
    icon: "🔶",
    bar: "bg-orange-500",
    width: "w-[50%]",
  },
  high: {
    label: "High Risk",
    bg: "bg-red-50 dark:bg-red-900/20",
    border: "border-red-200 dark:border-red-800",
    badge: "bg-red-100 dark:bg-red-800 text-red-800 dark:text-red-100",
    icon: "🚨",
    bar: "bg-red-500",
    width: "w-[75%]",
  },
  critical: {
    label: "Critical",
    bg: "bg-red-50 dark:bg-red-950/40",
    border: "border-red-400 dark:border-red-600",
    badge: "bg-red-600 text-white",
    icon: "🚫",
    bar: "bg-red-600",
    width: "w-full",
  },
};

const PATTERN_LABELS: Record<string, string> = {
  urgency: "⏰ Urgency pressure",
  impersonation: "🎭 Identity impersonation",
  phone_avoidance: "📵 Avoids callback",
  new_account: "🏦 New bank account",
  secrecy: "🤫 Secrecy demand",
  phishing_link: "🔗 Suspicious link",
  credential_request: "🔑 Credential request",
};

const TOOL_ICONS: Record<string, string> = {
  notify_trusted_contact: "👨‍👩‍👧 Notify family",
  suggest_callback: "📞 Suggest callback",
  generate_secret_question: "❓ Secret question",
  start_wait_timer: "⏱️ 2-min wait timer",
  create_incident_report: "📋 Incident report",
  block_payment_intent: "🚫 Block payment",
};

// ── Tool result types ────────────────────────────────────────────────────────

type ToolResultItem = {
  tool_name: string;
  success: boolean;
  data: Record<string, unknown>;
};

function isToolResult(r: unknown): r is ToolResultItem {
  return (
    typeof r === "object" &&
    r !== null &&
    "tool_name" in r &&
    "data" in r &&
    typeof (r as Record<string, unknown>).data === "object"
  );
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}
function num(v: unknown, fallback: number): number {
  return typeof v === "number" ? v : fallback;
}

// ── Sub-components ───────────────────────────────────────────────────────────

function CountdownTimer({ seconds, reason }: { seconds: number; reason: string }) {
  const [remaining, setRemaining] = useState(seconds);
  const done = remaining <= 0;

  useEffect(() => {
    if (done) return;
    const id = setInterval(() => setRemaining((r) => Math.max(0, r - 1)), 1000);
    return () => clearInterval(id);
  }, [done]);

  const mins = Math.floor(remaining / 60);
  const secs = remaining % 60;
  const pct = Math.round((remaining / seconds) * 100);

  return (
    <div className="rounded-xl border border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-950/30 p-4">
      <div className="flex items-center gap-3 mb-3">
        <span className="text-xl">⏱️</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-orange-800 dark:text-orange-200">
            {done ? "Pause complete — now you can verify" : "Pause before acting"}
          </p>
          <p className="text-xs text-orange-600 dark:text-orange-400 truncate">{reason}</p>
        </div>
        <span className="font-mono text-2xl font-bold text-orange-700 dark:text-orange-300 shrink-0">
          {done ? "✓" : `${mins}:${secs.toString().padStart(2, "0")}`}
        </span>
      </div>
      <div className="h-2 bg-orange-200 dark:bg-orange-900 rounded-full overflow-hidden">
        <div
          className="h-full bg-orange-500 rounded-full transition-all duration-1000"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function PaymentBlock({ message }: { message: string }) {
  return (
    <div className="rounded-xl border-2 border-red-400 dark:border-red-600 bg-red-50 dark:bg-red-950/40 p-4">
      <div className="flex gap-3 items-start">
        <span className="text-2xl shrink-0">🚫</span>
        <div>
          <p className="text-sm font-bold text-red-800 dark:text-red-200 mb-1">Payment Blocked</p>
          <p className="text-xs text-red-700 dark:text-red-300 leading-relaxed">{message}</p>
        </div>
      </div>
    </div>
  );
}

function SecretQuestion({
  question,
  relationship,
}: {
  question: string;
  relationship: string;
}) {
  const [revealed, setRevealed] = useState(false);
  return (
    <div className="rounded-xl border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-950/30 p-4">
      <div className="flex items-center gap-2 mb-2">
        <span>❓</span>
        <p className="text-sm font-semibold text-purple-800 dark:text-purple-200">
          Verification question for {relationship || "family member"}
        </p>
      </div>
      {revealed ? (
        <p className="text-sm text-purple-900 dark:text-purple-100 font-medium bg-white dark:bg-purple-900/40 rounded-lg px-3 py-2 leading-relaxed">
          &ldquo;{question}&rdquo;
        </p>
      ) : (
        <button
          onClick={() => setRevealed(true)}
          className="text-xs text-purple-600 dark:text-purple-400 underline underline-offset-2 hover:text-purple-800 dark:hover:text-purple-200 transition-colors"
        >
          Tap to reveal question
        </button>
      )}
    </div>
  );
}

function CallbackCard({ identity, message }: { identity: string; message: string }) {
  return (
    <div className="rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/30 p-4">
      <div className="flex items-center gap-2 mb-1">
        <span>📞</span>
        <p className="text-sm font-semibold text-blue-800 dark:text-blue-200">
          Call {identity || "them"} directly
        </p>
      </div>
      <p className="text-xs text-blue-700 dark:text-blue-300 leading-relaxed">{message}</p>
    </div>
  );
}

function NotificationCard({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/30 p-4">
      <div className="flex items-center gap-3">
        <span className="text-xl">👨‍👩‍👧</span>
        <div>
          <p className="text-sm font-semibold text-green-800 dark:text-green-200">Family notified</p>
          <p className="text-xs text-green-700 dark:text-green-300">{message}</p>
        </div>
      </div>
    </div>
  );
}

function IncidentCard({ incidentId, message }: { incidentId: string; message: string }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
      <span>📋</span>
      <div>
        <p className="text-xs font-mono font-semibold text-gray-700 dark:text-gray-200">{incidentId}</p>
        <p className="text-xs text-gray-500 dark:text-gray-400">{message}</p>
      </div>
    </div>
  );
}

// ── Tool results panel ───────────────────────────────────────────────────────

function ToolResultsPanel({ toolResults }: { toolResults: Record<string, unknown>[] }) {
  const items = toolResults.filter(isToolResult);
  if (items.length === 0) return null;

  return (
    <div className="px-6 pb-5 space-y-3">
      <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
        Active Protections
      </p>
      {items.map((r, i) => {
        const { tool_name, data } = r;
        const uiMsg = str(data.ui_message);

        switch (tool_name) {
          case "block_payment_intent":
            return <PaymentBlock key={i} message={uiMsg} />;
          case "start_wait_timer":
            return (
              <CountdownTimer
                key={i}
                seconds={num(data.duration_seconds, 120)}
                reason={str(data.reason)}
              />
            );
          case "generate_secret_question":
            return (
              <SecretQuestion
                key={i}
                question={str(data.verification_question)}
                relationship={str(data.claimed_relationship)}
              />
            );
          case "suggest_callback":
            return (
              <CallbackCard
                key={i}
                identity={str(data.claimed_identity)}
                message={uiMsg}
              />
            );
          case "notify_trusted_contact":
            return <NotificationCard key={i} message={uiMsg} />;
          case "create_incident_report":
            return (
              <IncidentCard
                key={i}
                incidentId={str(data.incident_id)}
                message={uiMsg}
              />
            );
          default:
            return null;
        }
      })}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface Props {
  result: AgentOutput;
}

export default function AnalysisResult({ result }: Props) {
  const [showReasoning, setShowReasoning] = useState(false);
  const cfg = RISK_CONFIG[result.risk_level] ?? RISK_CONFIG.low;

  return (
    <div className={`mt-8 rounded-2xl border-2 ${cfg.border} ${cfg.bg} overflow-hidden`}>
      {/* Risk header */}
      <div className="px-6 pt-6 pb-4">
        <div className="flex items-center gap-3 mb-3">
          <span className="text-2xl">{cfg.icon}</span>
          <span className={`px-3 py-1 rounded-full text-sm font-semibold ${cfg.badge}`}>
            {cfg.label}
          </span>
        </div>

        {/* Risk bar */}
        <div className="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full mb-5">
          <div className={`h-full rounded-full ${cfg.bar} ${cfg.width} transition-all duration-500`} />
        </div>

        {/* User message */}
        <p className="text-gray-800 dark:text-gray-200 text-sm leading-relaxed whitespace-pre-wrap">
          {result.user_message}
        </p>
      </div>

      {/* Patterns */}
      {result.patterns.length > 0 && (
        <div className="px-6 pb-4">
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
            Patterns Detected
          </p>
          <div className="flex flex-wrap gap-2">
            {result.patterns.map((p) => (
              <span
                key={p}
                className="text-xs px-2.5 py-1 rounded-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300"
              >
                {PATTERN_LABELS[p] ?? p}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Active protections (tool results) */}
      <ToolResultsPanel toolResults={result.tool_results} />

      {/* Actions triggered (tool call names summary) */}
      {result.tool_calls.length > 0 && (
        <div className="px-6 pb-4">
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
            Actions Triggered
          </p>
          <div className="flex flex-wrap gap-2">
            {result.tool_calls.map((tc, i) => (
              <span
                key={i}
                className="text-xs px-2.5 py-1 rounded-full bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300"
              >
                {TOOL_ICONS[tc.name] ?? tc.name}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Toggle reasoning */}
      <div className="px-6 pb-5">
        <button
          onClick={() => setShowReasoning(!showReasoning)}
          className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors underline underline-offset-2"
        >
          {showReasoning ? "Hide" : "Show"} Gemma 4 reasoning
        </button>
        {showReasoning && (
          <pre className="mt-3 text-xs text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-900 rounded-lg p-4 overflow-auto max-h-64 whitespace-pre-wrap font-mono leading-relaxed">
            {result.raw_reasoning}
          </pre>
        )}
      </div>
    </div>
  );
}
