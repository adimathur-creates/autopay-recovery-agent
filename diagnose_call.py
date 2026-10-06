"""
Finds out WHY a call is failing, by testing each piece separately.

Part 1: Calls your phone using Twilio ONLY (no Vapi). Twilio prints the exact error if it refuses.
Part 2: Shows the full details of your most recent Vapi call.
Part 3: Checks the phone number you imported into Vapi.

Needs these extra lines in .env:
  TWILIO_ACCOUNT_SID=AC...
  TWILIO_AUTH_TOKEN=...
  TWILIO_NUMBER=+1...

Run:  python diagnose_call.py
"""

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER", "").strip()
TEST_PHONE = os.getenv("TEST_PHONE", "").strip()
VAPI_KEY = os.getenv("VAPI_API_KEY", "").strip()
VAPI_PHONE_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "").strip()

print("=" * 60)
print("Quick format checks")
print("=" * 60)
print(f"TEST_PHONE      = {TEST_PHONE!r}  ->",
      "OK" if TEST_PHONE.startswith("+91") and len(TEST_PHONE) == 13 and TEST_PHONE[1:].isdigit()
      else "LOOKS WRONG (should be +91 then 10 digits, no spaces)")
print(f"TWILIO_NUMBER   = {TWILIO_NUMBER!r}  ->",
      "OK" if TWILIO_NUMBER.startswith("+") else "LOOKS WRONG (needs + and country code)")
print("TWILIO_ACCOUNT_SID ->", "OK" if SID.startswith("AC") else "LOOKS WRONG (must start with AC)")

print("\n" + "=" * 60)
print("PART 1: Twilio calls your phone directly (no Vapi)")
print("=" * 60)
if not (SID and TOKEN and TWILIO_NUMBER and TEST_PHONE):
    print("Skipped: add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_NUMBER to .env")
else:
    r = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Calls.json",
        auth=(SID, TOKEN),
        data={
            "To": TEST_PHONE,
            "From": TWILIO_NUMBER,
            "Twiml": "<Response><Say>Hello. This is a Twilio test call. Twilio is working.</Say></Response>",
        },
        timeout=30,
    )
    if r.status_code < 300:
        print("SUCCESS: Twilio accepted the call. Your phone should ring in a few seconds.")
        print("=> If it rings, Twilio is fine and the problem is the Vapi phone-number setup.")
        print("=> If it does NOT ring, the block is on your phone/carrier side.")
    else:
        err = r.json()
        print(f"TWILIO REFUSED. Code {err.get('code')}: {err.get('message')}")
        print(f"More info: {err.get('more_info')}")

print("\n" + "=" * 60)
print("PART 2: Your most recent Vapi call")
print("=" * 60)
if VAPI_KEY:
    r = requests.get("https://api.vapi.ai/call?limit=1",
                     headers={"Authorization": f"Bearer {VAPI_KEY}"}, timeout=30)
    calls = r.json() if r.ok else []
    if calls:
        c = calls[0]
        keep = {k: c.get(k) for k in ("status", "endedReason", "endedMessage", "phoneNumberId",
                                      "customer", "createdAt", "type")}
        print(json.dumps(keep, indent=2))
    else:
        print("No calls found or error:", r.status_code, r.text[:300])

print("\n" + "=" * 60)
print("PART 3: The phone number imported into Vapi")
print("=" * 60)
if VAPI_KEY and VAPI_PHONE_ID:
    r = requests.get(f"https://api.vapi.ai/phone-number/{VAPI_PHONE_ID}",
                     headers={"Authorization": f"Bearer {VAPI_KEY}"}, timeout=30)
    if r.ok:
        p = r.json()
        print(json.dumps({k: p.get(k) for k in ("provider", "number", "status",
                                                "twilioAccountSid", "name")}, indent=2))
        if p.get("twilioAccountSid") and SID and p["twilioAccountSid"] != SID:
            print("MISMATCH: Vapi is using a different Twilio Account SID than your .env!")
    else:
        print("Could not read the number:", r.status_code, r.text[:300])
        print("=> VAPI_PHONE_NUMBER_ID in .env is probably wrong.")
