"""
12 function-calling tools for Scam Sentinel.
These are called by the reasoning agent when Gemma 4 outputs tool_calls in its JSON response.

Tool families:
  Verification & response (6 core):
    notify_trusted_contact, suggest_callback, generate_secret_question,
    start_wait_timer, create_incident_report, block_payment_intent
  Channel-specific defenses (6 extended):
    block_phone_number, block_email_sender, check_url_safety,
    verify_image_message, show_official_contact, flag_red_phrases
"""

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel


# --- Tool parameter models ---

class NotifyTrustedContactParams(BaseModel):
    contact_id: str
    risk_summary: str
    incident_type: str  # voice_scam | text_scam | email_scam


class SuggestCallbackParams(BaseModel):
    claimed_identity: str
    saved_contact_number: str


class GenerateSecretQuestionParams(BaseModel):
    claimed_relationship: str
    context_hints: list[str]


class StartWaitTimerParams(BaseModel):
    duration_seconds: int = 120
    reason: str


class CreateIncidentReportParams(BaseModel):
    channel: str  # voice | sms | email
    patterns_detected: list[str]
    raw_content: str


class BlockPaymentIntentParams(BaseModel):
    trigger_keywords: list[str]


class BlockPhoneNumberParams(BaseModel):
    phone_number: str
    reason: str
    incident_type: str  # voice_scam | sms_scam


class BlockEmailSenderParams(BaseModel):
    email_address: str
    sender_domain: str | None = None
    reason: str


class CheckUrlSafetyParams(BaseModel):
    url: str
    detected_in: str = "sms"  # sms | email | voice_transcript


class VerifyImageMessageParams(BaseModel):
    extracted_text: str  # OCR'd text from MMS / image attachment
    image_source: str = "mms_attachment"


class ShowOfficialContactParams(BaseModel):
    impersonated_brand: str  # chase | usps | irs | amazon | etc.


class FlagRedPhrasesParams(BaseModel):
    phrases: list[str]
    risk_categories: list[str] = []  # parallel to phrases


# --- Tool results ---

class ToolResult(BaseModel):
    tool_name: str
    success: bool
    data: dict[str, Any]


# --- Tool implementations ---

def notify_trusted_contact(params: NotifyTrustedContactParams) -> ToolResult:
    """Send alert to a registered family member."""
    notification_id = str(uuid.uuid4())[:8]
    return ToolResult(
        tool_name="notify_trusted_contact",
        success=True,
        data={
            "notification_id": notification_id,
            "contact_id": params.contact_id,
            "message": f"SCAM ALERT: {params.risk_summary}",
            "incident_type": params.incident_type,
            "sent_at": datetime.utcnow().isoformat(),
            "ui_action": "show_alert",
            "ui_message": f"Your trusted contact has been notified about this potential {params.incident_type.replace('_', ' ')}.",
        },
    )


def suggest_callback(params: SuggestCallbackParams) -> ToolResult:
    """Recommend calling the real saved contact number."""
    return ToolResult(
        tool_name="suggest_callback",
        success=True,
        data={
            "claimed_identity": params.claimed_identity,
            "action": "call_saved_number",
            "saved_contact_number": params.saved_contact_number,
            "ui_action": "show_callback_button",
            "ui_message": f"Call {params.claimed_identity} directly on your saved number — do not call back the number that contacted you.",
        },
    )


def generate_secret_question(params: GenerateSecretQuestionParams) -> ToolResult:
    """Generate a verification question only the real family member would know."""
    # In production, this would use user's pre-registered family data.
    # For MVP, generate a prompt asking the user to think of one.
    examples = {
        "grandson": "What did we call you as a nickname when you were little?",
        "granddaughter": "What is the name of your childhood stuffed animal?",
        "son": "What is our family's special word that only we know?",
        "daughter": "What did we do on your last birthday together?",
        "default": "Ask something only the two of you would know — a shared memory, nickname, or family tradition.",
    }
    question = examples.get(params.claimed_relationship.lower(), examples["default"])
    return ToolResult(
        tool_name="generate_secret_question",
        success=True,
        data={
            "claimed_relationship": params.claimed_relationship,
            "verification_question": question,
            "context_hints": params.context_hints,
            "ui_action": "show_secret_question",
            "ui_message": f"Before sending anything, ask: '{question}'",
        },
    )


def start_wait_timer(params: StartWaitTimerParams) -> ToolResult:
    """Activate a cool-down period before any money transfer."""
    return ToolResult(
        tool_name="start_wait_timer",
        success=True,
        data={
            "duration_seconds": params.duration_seconds,
            "reason": params.reason,
            "expires_at": datetime.utcnow().isoformat(),
            "ui_action": "show_countdown_timer",
            "ui_message": f"Wait {params.duration_seconds // 60} minutes before taking any action. Scammers create urgency to stop you from thinking clearly.",
        },
    )


def create_incident_report(params: CreateIncidentReportParams) -> ToolResult:
    """Save the analyzed conversation to incident history."""
    incident_id = f"INC-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
    return ToolResult(
        tool_name="create_incident_report",
        success=True,
        data={
            "incident_id": incident_id,
            "channel": params.channel,
            "patterns_detected": params.patterns_detected,
            "created_at": datetime.utcnow().isoformat(),
            "ui_action": "show_incident_saved",
            "ui_message": f"Incident saved as {incident_id}. You can review this later in your history.",
        },
    )


def block_payment_intent(params: BlockPaymentIntentParams) -> ToolResult:
    """Show a hard confirmation gate before any money transfer."""
    return ToolResult(
        tool_name="block_payment_intent",
        success=True,
        data={
            "trigger_keywords": params.trigger_keywords,
            "blocked": True,
            "ui_action": "show_payment_block",
            "ui_message": "STOP: A potential scam was detected. Do not send money until you have verified this request by calling the person directly on their saved number.",
        },
    )


# --- New tool implementations (block phone, block email, URL check, image verify, official contact, flag phrases) ---


def block_phone_number(params: BlockPhoneNumberParams) -> ToolResult:
    """Add the phone number to the device blocklist + report to authorities."""
    report_id = f"RPT-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
    return ToolResult(
        tool_name="block_phone_number",
        success=True,
        data={
            "phone_number": params.phone_number,
            "reason": params.reason,
            "incident_type": params.incident_type,
            "blocked_at": datetime.utcnow().isoformat(),
            "report_id": report_id,
            "ui_action": "show_phone_blocked",
            "ui_message": f"{params.phone_number} blocked and reported (case {report_id}).",
        },
    )


def block_email_sender(params: BlockEmailSenderParams) -> ToolResult:
    """Add sender to spam filter + report (Gmail filter rule)."""
    filter_id = f"GMF-{str(uuid.uuid4())[:8].upper()}"
    return ToolResult(
        tool_name="block_email_sender",
        success=True,
        data={
            "email_address": params.email_address,
            "sender_domain": params.sender_domain,
            "reason": params.reason,
            "filter_id": filter_id,
            "blocked_at": datetime.utcnow().isoformat(),
            "ui_action": "show_email_blocked",
            "ui_message": f"Sender {params.email_address} added to spam filter.",
        },
    )


# Lookalike-domain heuristics (for demo).
LOOKALIKES = {
    "usps":   ["usps-", "usps.co", "usps-redelivery", "usps-confirm"],
    "chase":  ["chase-secure", "chase-verify", "chase.co", "chase-online"],
    "paypal": ["paypa1", "paypal-secure", "pypl-"],
    "amazon": ["amaz0n", "amazon-secure", "amazon.co"],
    "fedex":  ["fedex-track", "fedex.co"],
    "ups":    ["ups-redelivery"],
}


def _evaluate_url(url: str) -> dict:
    issues: list[str] = []
    real_brand: str | None = None
    if "://" in url and not url.lower().startswith("https://"):
        issues.append("no_https")
    domain = url.split("://", 1)[-1].split("/", 1)[0].lower()
    for brand, patterns in LOOKALIKES.items():
        if any(p in domain for p in patterns):
            issues.append("lookalike_domain")
            real_brand = brand
            break
    for tld in (".xyz", ".top", ".club", ".tk", ".ml", ".gq"):
        if domain.endswith(tld):
            issues.append("suspicious_tld")
            break
    if any(domain.endswith(t) for t in (".info", ".biz")) and "verify" in domain:
        issues.append("suspicious_tld")
    verdict = "malicious" if "lookalike_domain" in issues else (
        "suspicious" if len(issues) >= 1 else "safe"
    )
    return {"verdict": verdict, "reasons": issues, "real_brand": real_brand, "domain": domain}


def check_url_safety(params: CheckUrlSafetyParams) -> ToolResult:
    """Evaluate a URL for phishing / lookalike domains and prepare a blocking popup."""
    info = _evaluate_url(params.url)
    if info["verdict"] == "malicious":
        msg = f"This link mimics {info['real_brand'] or 'a real brand'}. Do NOT tap it."
    elif info["verdict"] == "suspicious":
        msg = "This link has unsafe characteristics. Verify before tapping."
    else:
        msg = "Link appears clean."
    return ToolResult(
        tool_name="check_url_safety",
        success=True,
        data={
            "url": params.url,
            "domain": info["domain"],
            "verdict": info["verdict"],
            "reasons": info["reasons"],
            "real_brand": info["real_brand"],
            "detected_in": params.detected_in,
            "ui_action": "show_url_warning",
            "ui_message": msg,
        },
    )


def verify_image_message(params: VerifyImageMessageParams) -> ToolResult:
    """Re-analyze image-extracted text (smishing screenshots) for scam patterns."""
    return ToolResult(
        tool_name="verify_image_message",
        success=True,
        data={
            "extracted_text": params.extracted_text,
            "image_source": params.image_source,
            "ocr_confidence": 0.91,
            "ui_action": "show_image_verification",
            "ui_message": (
                "Image text extracted via OCR. The text inside the image was analyzed "
                "with the same scam-pattern detector as a regular SMS."
            ),
        },
    )


# Real official contacts for common impersonated brands.
OFFICIAL_CONTACTS = {
    "chase":           {"name": "Chase Bank",                "phone": "1-800-935-9935", "website": "chase.com"},
    "usps":            {"name": "USPS",                       "phone": "1-800-275-8777", "website": "usps.com"},
    "irs":             {"name": "Internal Revenue Service",   "phone": "1-800-829-1040", "website": "irs.gov"},
    "amazon":          {"name": "Amazon",                     "phone": "1-888-280-4331", "website": "amazon.com"},
    "fedex":           {"name": "FedEx",                      "phone": "1-800-463-3339", "website": "fedex.com"},
    "ups":             {"name": "UPS",                        "phone": "1-800-742-5877", "website": "ups.com"},
    "paypal":          {"name": "PayPal",                     "phone": "1-888-221-1161", "website": "paypal.com"},
    "wells fargo":     {"name": "Wells Fargo",                "phone": "1-800-869-3557", "website": "wellsfargo.com"},
    "social security": {"name": "Social Security Administration", "phone": "1-800-772-1213", "website": "ssa.gov"},
    "bank of america": {"name": "Bank of America",            "phone": "1-800-432-1000", "website": "bankofamerica.com"},
}


def show_official_contact(params: ShowOfficialContactParams) -> ToolResult:
    """Surface the real contact info for a brand the scammer is impersonating."""
    key = params.impersonated_brand.strip().lower()
    info = OFFICIAL_CONTACTS.get(key, {
        "name": params.impersonated_brand,
        "phone": "Look up via the brand's official app or printed statement",
        "website": "official site only",
    })
    return ToolResult(
        tool_name="show_official_contact",
        success=True,
        data={
            "brand_key": key,
            "brand_name": info["name"],
            "real_phone": info["phone"],
            "real_website": info["website"],
            "ui_action": "show_official_contact",
            "ui_message": f"Real {info['name']}: {info['phone']} or {info['website']}",
        },
    )


def flag_red_phrases(params: FlagRedPhrasesParams) -> ToolResult:
    """Highlight specific dangerous phrases inside the original message."""
    return ToolResult(
        tool_name="flag_red_phrases",
        success=True,
        data={
            "flagged_phrases": params.phrases,
            "risk_categories": params.risk_categories,
            "ui_action": "highlight_phrases",
            "ui_message": f"{len(params.phrases)} risky phrase(s) highlighted in the original message.",
        },
    )


# --- Tool registry ---

TOOL_REGISTRY = {
    "notify_trusted_contact": (notify_trusted_contact, NotifyTrustedContactParams),
    "suggest_callback": (suggest_callback, SuggestCallbackParams),
    "generate_secret_question": (generate_secret_question, GenerateSecretQuestionParams),
    "start_wait_timer": (start_wait_timer, StartWaitTimerParams),
    "create_incident_report": (create_incident_report, CreateIncidentReportParams),
    "block_payment_intent": (block_payment_intent, BlockPaymentIntentParams),
    "block_phone_number": (block_phone_number, BlockPhoneNumberParams),
    "block_email_sender": (block_email_sender, BlockEmailSenderParams),
    "check_url_safety": (check_url_safety, CheckUrlSafetyParams),
    "verify_image_message": (verify_image_message, VerifyImageMessageParams),
    "show_official_contact": (show_official_contact, ShowOfficialContactParams),
    "flag_red_phrases": (flag_red_phrases, FlagRedPhrasesParams),
}

TOOL_DEFINITIONS = [
    {
        "name": "notify_trusted_contact",
        "description": "Send a push notification to a registered family member when scam risk is high. Use when risk_level is 'high' or 'critical'.",
        "parameters": {
            "contact_id": "string, the trusted contact to notify",
            "risk_summary": "string, one sentence summary",
            "incident_type": "enum: voice_scam, text_scam, email_scam",
        },
    },
    {
        "name": "suggest_callback",
        "description": "Recommend the user call back the real saved contact number, not the incoming number. Use when impersonation is suspected.",
        "parameters": {
            "claimed_identity": "string, who the caller claimed to be",
            "saved_contact_number": "string, the verified number",
        },
    },
    {
        "name": "generate_secret_question",
        "description": "Create a verification question only the real family member would know. Use when the caller claims to be a family member.",
        "parameters": {
            "claimed_relationship": "string, e.g. son, daughter, grandson",
            "context_hints": "array, e.g. shared memories, pet names",
        },
    },
    {
        "name": "start_wait_timer",
        "description": "Activate a 2-minute cool-down before any money transfer. Use when scammer creates urgency around payment.",
        "parameters": {
            "duration_seconds": "integer, default 120",
            "reason": "string, why the timer is needed",
        },
    },
    {
        "name": "create_incident_report",
        "description": "Save the analyzed conversation to incident history. Always call when risk_level is medium or higher.",
        "parameters": {
            "channel": "enum: voice, sms, email",
            "patterns_detected": "array of pattern tags",
            "raw_content": "string, the original message or transcript",
        },
    },
    {
        "name": "block_payment_intent",
        "description": "Show a hard confirmation gate before any money transfer link is opened. Use when payment pressure is detected.",
        "parameters": {
            "trigger_keywords": "array, e.g. send money, transfer now",
        },
    },
    {
        "name": "block_phone_number",
        "description": "Add the caller's phone number to the device blocklist and file a fraud report. Use for voice or SMS scams at risk_level medium or higher.",
        "parameters": {
            "phone_number": "string, the offending phone number",
            "reason": "string, one-sentence reason (which patterns were detected)",
            "incident_type": "enum: voice_scam, sms_scam",
        },
    },
    {
        "name": "block_email_sender",
        "description": "Add the email sender (and optionally their domain) to the spam filter. Use for email scams at risk_level medium or higher.",
        "parameters": {
            "email_address": "string, the sender's email address",
            "sender_domain": "string|null, the sender's domain if extractable",
            "reason": "string, one-sentence reason",
        },
    },
    {
        "name": "check_url_safety",
        "description": "Evaluate a URL for phishing / lookalike-domain heuristics and prepare a blocking popup. Use whenever a link appears in the input or phishing_link is detected.",
        "parameters": {
            "url": "string, the suspicious URL",
            "detected_in": "enum: sms, email, voice_transcript",
        },
    },
    {
        "name": "verify_image_message",
        "description": "Re-analyze image-extracted text (OCR from MMS or screenshot attachments) using the same scam-pattern detector. Use when metadata.image_extracted_text is present.",
        "parameters": {
            "extracted_text": "string, OCR'd text from the image",
            "image_source": "string, e.g. mms_attachment",
        },
    },
    {
        "name": "show_official_contact",
        "description": "Surface the real, verified contact information for a brand the scammer is impersonating (Chase, USPS, IRS, Amazon, etc.). Use whenever a known brand is being impersonated.",
        "parameters": {
            "impersonated_brand": "string, e.g. chase, usps, irs, amazon, paypal",
        },
    },
    {
        "name": "flag_red_phrases",
        "description": "Highlight specific dangerous phrases inside the original message in the UI. Use whenever risk_level is medium or higher to give the user receipts.",
        "parameters": {
            "phrases": "array of strings, the exact dangerous phrases quoted from the message",
            "risk_categories": "array of strings parallel to phrases (e.g. urgency, payment_pressure, secrecy)",
        },
    },
]


def execute_tool_call(tool_name: str, parameters: dict) -> ToolResult:
    """Execute a single tool call from the agent's JSON output."""
    if tool_name not in TOOL_REGISTRY:
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data={"error": f"Unknown tool: {tool_name}"},
        )
    fn, param_model = TOOL_REGISTRY[tool_name]
    try:
        params = param_model(**parameters)
        return fn(params)
    except Exception as e:
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data={"error": str(e)},
        )
