"""
One-time setup: creates the voice agent ("Asha") inside your Vapi account.

Run:  python setup_vapi.py
It prints an ASSISTANT ID. Paste that into your .env file as VAPI_ASSISTANT_ID.

Why a script instead of clicking in the dashboard? It makes the agent reproducible:
anyone reviewing the repo can see exactly how it is configured.
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

VAPI_API_KEY = os.environ["VAPI_API_KEY"]
PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")  # your ngrok URL
WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")
SERVER = {"url": f"{PUBLIC_URL}/vapi/webhook", "headers": {"x-vapi-secret": WEBHOOK_SECRET}}

system_prompt = (Path(__file__).parent / "prompts" / "system_prompt.md").read_text()


def fn_tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
        "server": SERVER,
    }


customer_id = {"type": "string", "description": "The customer ID given in the prompt, e.g. CUST001"}

tools = [
    fn_tool(
        "send_payment_link",
        "Create a secure Razorpay payment link for the amount due and send it to the customer by SMS.",
        {"customer_id": customer_id},
        ["customer_id"],
    ),
    fn_tool(
        "schedule_callback",
        "Schedule a callback at a time the person asked for.",
        {"customer_id": customer_id,
         "callback_time": {"type": "string", "description": "When to call back, e.g. 'tomorrow 6 pm'"}},
        ["customer_id", "callback_time"],
    ),
    fn_tool(
        "escalate_to_human",
        "Hand the case to a human support specialist. Use for disputes, fraud claims, or angry customers.",
        {"customer_id": customer_id,
         "reason": {"type": "string", "description": "Short reason for escalation"}},
        ["customer_id", "reason"],
    ),
    fn_tool(
        "log_outcome",
        "Record the final outcome of the call. Must be called exactly once before ending every call.",
        {
            "customer_id": customer_id,
            "outcome": {
                "type": "string",
                "enum": ["paid_via_link", "link_sent", "promise_to_pay", "auto_retry_scheduled",
                         "claims_already_paid", "disputed", "cancel_requested",
                         "callback_requested", "wrong_person", "do_not_call", "no_resolution"],
            },
            "promise_date": {"type": "string", "description": "YYYY-MM-DD, only for promise_to_pay"},
            "notes": {"type": "string", "description": "One line: key detail, e.g. UTR number or reason"},
        },
        ["customer_id", "outcome"],
    ),
    {"type": "endCall"},
]

assistant = {
    "name": "Asha - Autopay Recovery",
    "firstMessage": "Hello, this is Asha calling from {{merchant_name}}. Am I speaking with {{customer_name}}?",
    "model": {
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.3,
        "messages": [{"role": "system", "content": system_prompt}],
        "tools": tools,
    },
    "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "multi"},
    "voice": {"provider": "azure", "voiceId": "hi-IN-SwaraNeural"},
    "server": SERVER,
    "serverMessages": ["tool-calls", "end-of-call-report"],
    "maxDurationSeconds": 240,
    "endCallMessage": "Thank you for your time. Have a good day.",
}

resp = requests.post(
    "https://api.vapi.ai/assistant",
    headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
    json=assistant,
    timeout=30,
)
if resp.status_code >= 300:
    print("Vapi returned an error:\n", resp.status_code, resp.text)
    raise SystemExit(1)

print("\nAssistant created.")
print("Add this line to your .env file:\n")
print(f"VAPI_ASSISTANT_ID={resp.json()['id']}\n")
