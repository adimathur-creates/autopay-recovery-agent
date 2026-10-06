"""
Start real phone calls from the agent.

SAFETY: every call goes to TEST_PHONE (your own number) from .env.
The fictional customers' phone numbers are never dialled.

Examples:
  python make_calls.py --customer CUST001        # call for one customer
  python make_calls.py --all                     # go through all 10 (one by one)
  python make_calls.py --customer CUST002 --ignore-hours   # testing at night

Guardrails built in (what a real merchant deployment needs):
  - Skips customers on the do-not-call list
  - Only calls between 9 AM and 7 PM India time (override only for your own testing)
  - Stops after 3 attempts per customer
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from amount_words import to_words_en, to_words_hi

load_dotenv()

# Which voice platform to use: "bolna" (default, calls Indian numbers on the free tier) or "vapi"
PROVIDER = os.getenv("VOICE_PROVIDER", "bolna").lower()
TEST_PHONE = os.environ["TEST_PHONE"]

CALL_START_HOUR, CALL_END_HOUR = 9, 19
MAX_ATTEMPTS = 3

customers = json.loads((Path(__file__).parent / "data" / "customers.json").read_text())

FIRST_MESSAGE = {
    "English": "Hello, this is Asha calling from {merchant}. Am I speaking with {name}?",
    "Hindi": "नमस्ते, मैं आशा बोल रही हूँ {merchant} से। क्या मेरी बात {name} जी से हो रही है?",
}


def check_guardrails(c, ignore_hours):
    if c["do_not_call"]:
        return "on do-not-call list"
    if c["attempts_so_far"] >= MAX_ATTEMPTS:
        return f"already tried {MAX_ATTEMPTS} times"
    hour = datetime.now(ZoneInfo("Asia/Kolkata")).hour
    if not ignore_hours and not (CALL_START_HOUR <= hour < CALL_END_HOUR):
        return "outside calling hours (9 AM - 7 PM IST)"
    return None


def call_variables(c):
    """The customer details the agent's prompt needs ({{customer_name}} etc.)."""
    return {
        "customer_id": c["customer_id"],
        "customer_name": c["name"],
        "language": c["language"],
        "merchant_name": c["merchant_name"],
        "plan": c["plan"].replace(" (monthly)", " monthly plan"),   # spoken form, no brackets
        "amount_inr": str(c["amount_inr"]),
        "amount_words_en": to_words_en(c["amount_inr"]),   # server converts; the AI only reads it
        "amount_words_hi": to_words_hi(c["amount_inr"]),
        "mandate_type": c["mandate_type"],
        "failure_reason": c["failure_reason"],
        "failed_on": datetime.strptime(c["failed_on"], "%Y-%m-%d").strftime("%-d %B %Y"),
        "agent_language": "hi" if c["language"] == "Hindi" else "en",
        "today": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d"),
        "first_message": FIRST_MESSAGE.get(c["language"], FIRST_MESSAGE["English"]).format(
            merchant=c["merchant_name"], name=c["name"]),
    }


def place_call_bolna(c):
    body = {
        "agent_id": os.environ["BOLNA_AGENT_ID"],
        "recipient_phone_number": TEST_PHONE,
        "user_data": call_variables(c),
    }
    resp = requests.post("https://api.bolna.ai/call",
                         headers={"Authorization": f"Bearer {os.environ['BOLNA_API_KEY']}"},
                         json=body, timeout=30)
    if resp.status_code >= 300:
        print(f"  ERROR from Bolna: {resp.status_code} {resp.text}")
    else:
        print(f"  Call started. Bolna response: {resp.text[:200]}")


def place_call_vapi(c):
    variables = call_variables(c)
    body = {
        "assistantId": os.environ["VAPI_ASSISTANT_ID"],
        "phoneNumberId": os.environ["VAPI_PHONE_NUMBER_ID"],
        "customer": {"number": TEST_PHONE, "name": c["name"]},
        "assistantOverrides": {
            "firstMessage": variables.pop("first_message"),
            "variableValues": variables,
        },
    }
    resp = requests.post("https://api.vapi.ai/call",
                         headers={"Authorization": f"Bearer {os.environ['VAPI_API_KEY']}"},
                         json=body, timeout=30)
    if resp.status_code >= 300:
        print(f"  ERROR from Vapi: {resp.status_code} {resp.text}")
    else:
        print(f"  Call started. Vapi call id: {resp.json().get('id')}")


def place_call(c):
    place_call_vapi(c) if PROVIDER == "vapi" else place_call_bolna(c)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--customer", help="Customer ID, e.g. CUST001")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--ignore-hours", action="store_true",
                        help="Only for testing on your own number")
    args = parser.parse_args()

    targets = customers if args.all else [c for c in customers if c["customer_id"] == args.customer]
    if not targets:
        raise SystemExit(f"No customer with id {args.customer}")

    for c in targets:
        print(f"{c['customer_id']} {c['name']} ({c['failure_reason']}):")
        reason = check_guardrails(c, args.ignore_hours)
        if reason:
            print(f"  SKIPPED - {reason}")
            continue
        place_call(c)
        if args.all:
            input("  Press Enter when this call has ended to start the next one...")
            time.sleep(1)


if __name__ == "__main__":
    main()
