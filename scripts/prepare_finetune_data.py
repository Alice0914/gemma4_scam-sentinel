"""
Convert train.jsonl to chat template format for Unsloth LoRA fine-tuning.
Generates templated CoT reasoning + JSON output for each training sample.

Usage:
    python scripts/prepare_finetune_data.py \
        --input data/synthetic/train.jsonl \
        --output data/synthetic/train_chat.jsonl
"""

import json
import argparse
from pathlib import Path

SYSTEM_PROMPT_PATH = Path("backend/prompts/system_prompt.md")

RISK_LEVEL_MAP = {
    "family_impersonation": "critical",
    "prosecutor_scam": "critical",
    "bec_scam": "high",
    "romance_scam": "high",
    "bank_phishing": "high",
    "phishing_link": "medium",
    "package_scam": "medium",
    "normal": "safe",
}

PATTERN_EXPLANATIONS = {
    "urgency": "The message creates pressure to act immediately, which is a common manipulation tactic.",
    "impersonation": "The sender claims to be someone trusted but is using an unknown or unusual channel.",
    "secrecy": "The sender demands you keep this secret from family — a hallmark of manipulation.",
    "phone_avoidance": "The sender discourages a callback, preventing you from verifying their identity.",
    "new_account": "The sender requests payment to an unfamiliar bank account.",
    "phishing_link": "The message contains a suspicious link that may lead to a fake website.",
    "credential_request": "The sender asks for sensitive information no legitimate institution would request by message.",
}

TOOL_MAP = {
    "critical": [
        {"name": "notify_trusted_contact", "parameters": {"contact_id": "primary_family", "risk_summary": "High-risk scam attempt detected", "incident_type": "text_scam"}},
        {"name": "suggest_callback", "parameters": {"claimed_identity": "sender", "saved_contact_number": "use saved contact"}},
        {"name": "generate_secret_question", "parameters": {"claimed_relationship": "family member", "context_hints": ["shared memories"]}},
        {"name": "start_wait_timer", "parameters": {"duration_seconds": 120, "reason": "Urgent money request — pause before acting"}},
        {"name": "create_incident_report", "parameters": {"channel": "sms", "patterns_detected": [], "raw_content": ""}},
        {"name": "block_payment_intent", "parameters": {"trigger_keywords": ["send", "transfer", "pay"]}},
    ],
    "high": [
        {"name": "suggest_callback", "parameters": {"claimed_identity": "sender", "saved_contact_number": "use saved contact"}},
        {"name": "start_wait_timer", "parameters": {"duration_seconds": 120, "reason": "Suspicious request — pause before acting"}},
        {"name": "create_incident_report", "parameters": {"channel": "sms", "patterns_detected": [], "raw_content": ""}},
        {"name": "block_payment_intent", "parameters": {"trigger_keywords": ["send", "transfer", "pay"]}},
    ],
    "medium": [
        {"name": "create_incident_report", "parameters": {"channel": "sms", "patterns_detected": [], "raw_content": ""}},
        {"name": "block_payment_intent", "parameters": {"trigger_keywords": ["click", "pay", "verify"]}},
    ],
    "low": [
        {"name": "create_incident_report", "parameters": {"channel": "sms", "patterns_detected": [], "raw_content": ""}},
    ],
    "safe": [],
}


def build_assistant_response(sample: dict) -> str:
    category = sample["category"]
    patterns = sample.get("patterns", [])
    text = sample["text"]
    risk_level = RISK_LEVEL_MAP.get(category, "medium")

    if not patterns:
        reasoning = (
            "Step 1 - IDENTIFY: No scam patterns detected in this message.\n"
            "Step 2 - ASSESS: No patterns present. Risk level: safe.\n"
            "Step 3 - EXPLAIN: This appears to be a normal message.\n"
            "Step 4 - TOOLS: No tools needed.\n"
            "Step 5 - FOUR QUESTIONS: This message does not appear to be a scam."
        )
        user_message = "This message looks normal. No warning signs detected."
        tool_calls = []
    else:
        pattern_lines = "\n".join(
            f"  - {p}: {PATTERN_EXPLANATIONS.get(p, 'Suspicious pattern detected.')}"
            for p in patterns
        )
        reasoning = (
            f"Step 1 - IDENTIFY: The following patterns are present:\n{pattern_lines}\n"
            f"Step 2 - ASSESS: {len(patterns)} pattern(s) detected, risk level: {risk_level}.\n"
            f"Step 3 - EXPLAIN: Each pattern identified above represents a manipulation tactic.\n"
            f"Step 4 - TOOLS: Calling appropriate tools for {risk_level} risk.\n"
            f"Step 5 - FOUR QUESTIONS: This message shows warning signs of a {category.replace('_', ' ')}. "
            f"Do not act immediately. Verify through a trusted channel."
        )
        why_dangerous = " ".join(
            PATTERN_EXPLANATIONS.get(p, "") for p in patterns[:3]
        )
        user_message = (
            f"This message shows warning signs of a {category.replace('_', ' ')}.\n\n"
            f"Why it's dangerous: {why_dangerous}\n\n"
            f"Do this right now: Do not respond or send anything. Verify by contacting the sender "
            f"through a trusted, independently looked-up channel.\n\n"
            f"To verify: Call the person back on their saved number, not the number that contacted you."
        )
        tool_calls = TOOL_MAP.get(risk_level, [])
        # Fill in dynamic fields
        for tc in tool_calls:
            if tc["name"] == "create_incident_report":
                tc["parameters"]["patterns_detected"] = patterns
                tc["parameters"]["raw_content"] = text[:200]

    output_json = {
        "risk_level": risk_level,
        "patterns": patterns,
        "user_message": user_message,
        "tool_calls": tool_calls,
    }

    return f"{reasoning}\n\n```json\n{json.dumps(output_json, indent=2, ensure_ascii=False)}\n```"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/synthetic/train.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/synthetic/train_chat.jsonl"))
    args = parser.parse_args()

    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0

    with open(args.input, encoding="utf-8-sig") as f_in, \
         open(args.output, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            sample = json.loads(line)
            assistant_response = build_assistant_response(sample)
            chat_sample = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"ANALYZE THIS INPUT:\n\nTEXT: {sample['text']}\nMETADATA: {{\"channel\": \"{sample['channel']}\"}}"},
                    {"role": "assistant", "content": assistant_response},
                ]
            }
            f_out.write(json.dumps(chat_sample, ensure_ascii=False) + "\n")
            written += 1

    print(f"Wrote {written} chat samples to {args.output}")


if __name__ == "__main__":
    main()
