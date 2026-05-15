"use client";

import { useState } from "react";

const DEMO_SCENARIOS = [
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
    label: "✅ Normal family message",
    text: "Dad, can you send me $40 for groceries? I'll pay you back when I see you Sunday. My Venmo is @jake-miller22",
    channel: "sms",
  },
];

interface Props {
  onSubmit: (text: string, channel: string) => void;
  loading: boolean;
}

export default function InputForm({ onSubmit, loading }: Props) {
  const [text, setText] = useState("");
  const [channel, setChannel] = useState("sms");

  function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    if (text.trim()) onSubmit(text.trim(), channel);
  }

  function loadDemo(scenario: (typeof DEMO_SCENARIOS)[0]) {
    setText(scenario.text);
    setChannel(scenario.channel);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Demo buttons */}
      <div className="flex flex-wrap gap-2">
        {DEMO_SCENARIOS.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => loadDemo(s)}
            className="text-xs px-3 py-1.5 rounded-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:border-blue-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Textarea */}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={
          channel === "voice"
            ? "Enter the voice call transcript here…"
            : "Paste a suspicious message, email, or text here…"
        }
        rows={5}
        className="w-full px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
      />

      {/* Channel + submit row */}
      <div className="flex gap-3 items-center">
        <select
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
          className="text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="sms">SMS</option>
          <option value="email">Email</option>
          <option value="voice">Voice</option>
          <option value="chat">Chat</option>
        </select>
        <button
          type="submit"
          disabled={!text.trim() || loading}
          className="flex-1 py-2 px-6 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
        >
          {loading ? "Analyzing…" : "Analyze"}
        </button>
      </div>
    </form>
  );
}
