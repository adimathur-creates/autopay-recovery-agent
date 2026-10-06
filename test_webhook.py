"""
Tests the backend WITHOUT making any phone calls.

It pretends to be Vapi and sends the same messages Vapi would send during a call.
Start the server first (python app.py), then in a second terminal run:
    python test_webhook.py

Set SKIP_RAZORPAY=1 to test without Razorpay keys (skips the payment-link test).
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()
BASE = os.getenv("TEST_BASE_URL", "http://localhost:5000")
HEADERS = {"x-vapi-secret": os.getenv("VAPI_WEBHOOK_SECRET", "")}


def send_tool_call(name, arguments):
    payload = {"message": {"type": "tool-calls", "call": {"id": "test-call"},
                           "toolCallList": [{"id": f"t-{name}", "type": "function",
                                             "function": {"name": name, "arguments": arguments}}]}}
    r = requests.post(f"{BASE}/vapi/webhook", json=payload, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["results"][0]


passed = failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS  {label}")
    else:
        failed += 1
        print(f"FAIL  {label}  {detail}")


# 1. Server is up
check("server is running", requests.get(f"{BASE}/health", timeout=5).ok)

# 2. Identity guardrail: no link before verification, wrong year rejected, lock after 2 misses
res = send_tool_call("send_payment_link", {"customer_id": "CUST001"})
check("payment link BLOCKED before identity verified", "BLOCKED" in res.get("result", ""), res)
res = send_tool_call("verify_identity", {"customer_id": "CUST004", "birth_year": "1951"})
check("wrong birth year rejected", "NOT MATCHED" in res.get("result", ""), res)
res = send_tool_call("verify_identity", {"customer_id": "CUST004", "birth_year": "1950"})
check("second wrong year -> stop sharing details", "second time" in res.get("result", ""), res)
res = send_tool_call("verify_identity", {"customer_id": "CUST004", "birth_year": "1996"})
check("locked after 2 failures, even with right year", "LOCKED" in res.get("result", ""), res)
res = send_tool_call("verify_identity", {"customer_id": "CUST001", "birth_year": "nineteen 1994"})
check("correct year verified (digits extracted)", "VERIFIED" in res.get("result", ""), res)

# 2b. Payment link after verification (real Razorpay test-mode call)
if os.getenv("SKIP_RAZORPAY") != "1":
    res = send_tool_call("send_payment_link", {"customer_id": "CUST001"})
    check("payment link created via Razorpay", "result" in res and "sent" in res["result"], res)

# 3. Unknown customer is handled without crashing the call
res = send_tool_call("send_payment_link", {"customer_id": "NOPE"})
check("unknown customer handled safely", "result" in res and "Could not find" in res["result"], res)

# 4. Callback, escalation, outcome
check("schedule callback", "result" in send_tool_call(
    "schedule_callback", {"customer_id": "CUST009", "callback_time": "tomorrow 6 pm"}))
check("escalate dispute", "result" in send_tool_call(
    "escalate_to_human", {"customer_id": "CUST008", "reason": "does not recognise the charge"}))
check("log promise to pay", "result" in send_tool_call(
    "log_outcome", {"customer_id": "CUST002", "outcome": "promise_to_pay",
                    "promise_date": "2026-10-07", "notes": "salary on the 7th"}))

# 5. Arguments arriving as a JSON string (Vapi sometimes does this)
check("string arguments handled", "result" in send_tool_call(
    "log_outcome", '{"customer_id": "CUST005", "outcome": "auto_retry_scheduled"}'))

# 6. Wrong secret is rejected
r = requests.post(f"{BASE}/vapi/webhook", json={"message": {"type": "tool-calls"}},
                  headers={"x-vapi-secret": "wrong"}, timeout=5)
check("wrong secret rejected", r.status_code == 401 or not HEADERS["x-vapi-secret"],
      r.status_code)

# 7. Bolna path: per-tool URL with Bearer token
BOLNA_HEADERS = {"Authorization": f"Bearer {HEADERS['x-vapi-secret']}"}
r = requests.post(f"{BASE}/tools/log_outcome", headers=BOLNA_HEADERS, timeout=10,
                  json={"customer_id": "CUST007", "outcome": "cancel_requested",
                        "promise_date": "", "notes": "test"})
check("bolna tool endpoint", r.ok and "Outcome saved" in r.json().get("result", ""), r.text)

# 8. Bolna end-of-call webhook (cost arrives in cents)
r = requests.post(f"{BASE}/bolna/webhook", headers=BOLNA_HEADERS, timeout=10, json={
    "id": "test-exec", "status": "completed", "total_cost": 12.5, "conversation_duration": 80,
    "transcript": "assistant: hi\nuser: hello",
    "telephony_data": {"recording_url": "https://example.com/r.mp3"},
    "context_details": {"recipient_data": {"customer_id": "CUST007"}}})
calls = requests.get(f"{BASE}/api/metrics", timeout=30).json()["calls"]
check("bolna webhook saved, cents -> dollars",
      r.ok and any(c.get("call_id") == "test-exec" and c.get("cost_usd") == 0.125 for c in calls))

# 8b. Bolna webhook auth via ?token= (Bolna's API can't attach headers to the webhook)
r = requests.post(f"{BASE}/bolna/webhook?token={HEADERS['x-vapi-secret']}", timeout=10,
                  json={"id": "tok-exec", "status": "in-progress"})
r_bad = requests.post(f"{BASE}/bolna/webhook?token=wrong", timeout=10, json={"status": "in-progress"})
check("webhook accepts ?token=, rejects wrong token",
      r.ok and (r_bad.status_code == 401 or not HEADERS["x-vapi-secret"]), (r.status_code, r_bad.status_code))

# 9. Scenario check: CUST007 expected cancel_requested -> pass
rows = {x["customer_id"]: x for x in requests.get(f"{BASE}/api/metrics", timeout=30).json()["rows"]}
check("scenario check marks expected outcome as pass", rows["CUST007"]["check"] == "pass", rows["CUST007"])

# 10. Dashboard renders
check("dashboard loads", requests.get(f"{BASE}/", timeout=30).ok)

print(f"\n{passed} passed, {failed} failed")
print("Note: these tests write sample rows to data/outcomes.json. Delete that file before your real demo.")
