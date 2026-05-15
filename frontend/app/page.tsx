"use client";

import { useState } from "react";
import PhoneEmulator from "./components/PhoneEmulator";
import AnalysisPanel from "./components/AnalysisPanel";

export type PhoneState = "idle" | "preview" | "analyzing" | "result";

export interface AgentOutput {
  risk_level: "safe" | "low" | "medium" | "high" | "critical";
  patterns: string[];
  user_message: string;
  tool_calls: { name: string; parameters: Record<string, unknown> }[];
  tool_results: Record<string, unknown>[];
  raw_reasoning: string;
}

export interface Scenario {
  label: string;
  text: string;
  channel: string;
  metadata?: Record<string, unknown>;
}

const BACKEND = "http://localhost:8000";

export default function Home() {
  const [text, setText] = useState("");
  const [channel, setChannel] = useState("sms");
  const [metadata, setMetadata] = useState<Record<string, unknown> | undefined>(undefined);
  const [phoneState, setPhoneState] = useState<PhoneState>("idle");
  const [result, setResult] = useState<AgentOutput | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function analyze() {
    if (!text.trim()) return;
    setPhoneState("analyzing");
    setResult(null);
    setError(null);
    try {
      const isVoice = channel === "voice";
      const endpoint = `${BACKEND}${isVoice ? "/analyze/voice" : "/analyze/text"}`;
      const body = isVoice
        ? { transcript: text, metadata: { channel: "voice", ...(metadata ?? {}) } }
        : { text, channel, metadata };
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`Backend error ${res.status}`);
      const data: AgentOutput = await res.json();
      setResult(data);
      setPhoneState("result");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      setPhoneState(text ? "preview" : "idle");
    }
  }

  function loadScenario(scenario: Scenario) {
    setText(scenario.text);
    setChannel(scenario.channel);
    setMetadata(scenario.metadata);
    setPhoneState("preview");
    setResult(null);
    setError(null);
  }

  return (
    <main className="flex h-screen bg-gray-950 overflow-hidden">
      {/* Left: Phone emulator */}
      <div className="flex items-center justify-center w-[420px] shrink-0 border-r border-gray-800/60">
        <PhoneEmulator
          phoneState={phoneState}
          text={text}
          channel={channel}
          result={result}
        />
      </div>

      {/* Right: Analysis panel */}
      <div className="flex-1 overflow-hidden">
        <AnalysisPanel
          text={text}
          setText={setText}
          channel={channel}
          setChannel={setChannel}
          onAnalyze={analyze}
          onLoadScenario={loadScenario}
          phoneState={phoneState}
          result={result}
          error={error}
        />
      </div>
    </main>
  );
}
