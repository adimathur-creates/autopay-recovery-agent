"""
Autopay Recovery Agent - backend server.

What this file does, in plain words:
1. Vapi (the voice platform) calls this server whenever the voice agent uses a "tool"
   (for example: "send a payment link"). We do the real work here and reply with a short text.
2. It creates real Razorpay payment links (in TEST mode, so no real money moves).
3. It saves every call outcome to data/outcomes.json.
4. It shows a live dashboard at http://localhost:5000 with recovery numbers.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
VAPI_WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")
# All links and SMS go to YOUR number, never the fictional customer's number.
TEST_PHONE = os.getenv("TEST_PHONE", "")

DATA_DIR = Path(__file__).parent / "data"
CUSTOMERS_FILE = DATA_DIR / "customers.json"
OUTCOMES_FILE = DATA_DIR / "outcomes.json"

app = Flask(__name__)


# ---------- small helpers for reading / saving data ----------

def load_customers():
    return {c["customer_id"]: c for c in json.loads(CUSTOMERS_FILE.read_text())}


def load_outcomes():
    if not OUTCOMES_FILE.exists():
        return []
    return json.loads(OUTCOMES_FILE.read_text())


def save_event(event):
    """Append one event (link sent, outcome logged, etc.) to outcomes.json."""
    events = load_outcomes()
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    events.append(event)
    OUTCOMES_FILE.write_text(json.dumps(events, indent=2))


def now_ist_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------- Razorpay ----------

def create_razorpay_payment_link(customer):
    """Create a Razorpay Payment Link in test mode. Returns (link_id, short_url)."""
    body = {
        "amount": int(customer["amount_inr"]) * 100,  # Razorpay uses paise
        "currency": "INR",
        "accept_partial": False,
        "description": f"{customer['plan']} - missed autopay of {customer['failed_on']}",
        "customer": {
            "name": customer["name"],
            "contact": TEST_PHONE or customer["phone"],
            "email": customer["email"],
        },
        "notify": {"sms": True, "email": False},
        "reminder_enable": True,
        "reference_id": f"{customer['customer_id']}-{uuid.uuid4().hex[:8]}",
        "notes": {
            "customer_id": customer["customer_id"],
            "merchant": customer["merchant_name"],
            "failure_reason": customer["failure_reason"],
            "source": "autopay-recovery-voice-agent",
        },
    }
    resp = requests.post(
        "https://api.razorpay.com/v1/payment_links",
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
        json=body,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["id"], data["short_url"]


def get_payment_link_status(link_id):
    """Ask Razorpay whether a link has been paid. Returns e.g. 'created' or 'paid'."""
    try:
        resp = requests.get(
            f"https://api.razorpay.com/v1/payment_links/{link_id}",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("status", "unknown")
    except Exception:
        return "unknown"


# ---------- the tools the voice agent can use ----------

VERIFY_WINDOW_SEC = 15 * 60   # a verification is valid for 15 minutes
MAX_VERIFY_FAILURES = 2       # after 2 wrong answers, stop trying


def _recent_identity_events(customer_id):
    cutoff = datetime.now(timezone.utc).timestamp() - VERIFY_WINDOW_SEC
    return [e for e in load_outcomes()
            if e["type"] == "identity_check" and e["customer_id"] == customer_id
            and datetime.fromisoformat(e["timestamp"]).timestamp() >= cutoff]


def is_verified(customer_id):
    return any(e["result"] == "verified" for e in _recent_identity_events(customer_id))


def tool_verify_identity(args, call_id):
    """The AI never sees the real birth year. It sends what the caller said; the server compares."""
    customer = load_customers().get(args.get("customer_id", ""))
    if not customer:
        return "Could not find this customer. Apologise and offer a callback."

    failures = sum(1 for e in _recent_identity_events(customer["customer_id"]) if e["result"] == "not_matched")
    if failures >= MAX_VERIFY_FAILURES:
        return ("LOCKED: identity could not be verified. Do NOT share the amount, plan or any payment "
                "details. Follow the wrong-person rules: offer a callback, log outcome wrong_person.")

    said = "".join(ch for ch in str(args.get("birth_year", "")) if ch.isdigit())
    matched = len(said) == 4 and said == str(customer["birth_year"])
    save_event({
        "type": "identity_check",
        "call_id": call_id,
        "customer_id": customer["customer_id"],
        "result": "verified" if matched else "not_matched",
        "heard": said or "(none)",   # what the caller said, kept for audit
    })
    if matched:
        return "VERIFIED. You may now explain the failed payment."
    if failures + 1 >= MAX_VERIFY_FAILURES:
        return ("NOT MATCHED for the second time. Do NOT share any payment details. Follow the "
                "wrong-person rules: offer a callback, then log outcome wrong_person.")
    return ("NOT MATCHED. Do not share any payment details. Politely ask them to say their year of "
            "birth once more, slowly. They may say it in English or Hindi.")


def tool_send_payment_link(args, call_id):
    customers = load_customers()
    customer = customers.get(args.get("customer_id", ""))
    if not customer:
        return "Could not find this customer. Apologise and offer a callback."

    # Server-side guardrail: no payment link unless identity was verified on this server.
    if not is_verified(customer["customer_id"]):
        return "BLOCKED: identity is not verified. Call verify_identity first. Do not share payment details."

    # Idempotency: if this customer already has an unpaid link, re-use it instead of
    # creating a duplicate (LLMs sometimes call the same tool twice).
    for e in reversed(load_outcomes()):
        if e["type"] == "payment_link_sent" and e["customer_id"] == customer["customer_id"]:
            if get_payment_link_status(e["link_id"]) in ("created", "partially_paid"):
                return "A payment link was already sent to this customer. Tell them to check their SMS."
            break

    link_id, short_url = create_razorpay_payment_link(customer)
    save_event({
        "type": "payment_link_sent",
        "call_id": call_id,
        "customer_id": customer["customer_id"],
        "amount_inr": customer["amount_inr"],
        "link_id": link_id,
        "short_url": short_url,
    })
    return "Payment link created and sent to the customer by SMS."


def tool_schedule_callback(args, call_id):
    save_event({
        "type": "callback_scheduled",
        "call_id": call_id,
        "customer_id": args.get("customer_id"),
        "callback_time": args.get("callback_time", "not specified"),
    })
    return "Callback scheduled."


def tool_escalate_to_human(args, call_id):
    save_event({
        "type": "escalated",
        "call_id": call_id,
        "customer_id": args.get("customer_id"),
        "reason": args.get("reason", ""),
    })
    return "Escalated. A support specialist will contact the customer within 24 hours."


def tool_log_outcome(args, call_id):
    save_event({
        "type": "outcome",
        "call_id": call_id,
        "customer_id": args.get("customer_id"),
        "outcome": args.get("outcome", "no_resolution"),
        "promise_date": args.get("promise_date"),
        "notes": args.get("notes", ""),
    })
    return "Outcome saved. You can now thank the customer and end the call."


TOOLS = {
    "verify_identity": tool_verify_identity,
    "send_payment_link": tool_send_payment_link,
    "schedule_callback": tool_schedule_callback,
    "escalate_to_human": tool_escalate_to_human,
    "log_outcome": tool_log_outcome,
}


# ---------- the webhook Vapi talks to ----------

@app.post("/vapi/webhook")
def vapi_webhook():
    # Simple shared-secret check so random people can't hit this URL.
    if VAPI_WEBHOOK_SECRET and request.headers.get("x-vapi-secret") != VAPI_WEBHOOK_SECRET:
        return jsonify({"error": "unauthorised"}), 401

    message = (request.get_json(silent=True) or {}).get("message", {})
    msg_type = message.get("type")
    call_id = (message.get("call") or {}).get("id", "local-test")

    if msg_type == "tool-calls":
        results = []
        for tool_call in message.get("toolCallList", []):
            name = tool_call["function"]["name"]
            args = tool_call["function"].get("arguments") or {}
            if isinstance(args, str):  # sometimes arguments arrive as a JSON string
                args = json.loads(args or "{}")
            try:
                result = TOOLS[name](args, call_id) if name in TOOLS else f"Unknown tool {name}"
                results.append({"toolCallId": tool_call["id"], "result": result})
            except Exception as exc:  # never crash the live call
                app.logger.exception("tool failed")
                results.append({"toolCallId": tool_call["id"],
                                "error": f"Tool failed: {exc}. Apologise and offer a callback."})
        return jsonify({"results": results})

    if msg_type == "end-of-call-report":
        save_event({
            "type": "call_ended",
            "call_id": call_id,
            "customer_id": (((message.get("call") or {}).get("assistantOverrides") or {})
                            .get("variableValues") or {}).get("customer_id"),
            "ended_reason": message.get("endedReason"),
            "summary": (message.get("analysis") or {}).get("summary"),
            "cost_usd": message.get("cost"),
            "duration_sec": message.get("durationSeconds"),
            "recording_url": (message.get("artifact") or {}).get("recordingUrl")
                             or message.get("recordingUrl"),
        })
        return jsonify({"ok": True})

    return jsonify({"ok": True})


# ---------- Bolna (Indian voice platform) ----------
# Bolna calls one URL per tool, e.g. POST /tools/send_payment_link with JSON {"customer_id": "CUST001"}.
# The same tool functions above do the work, so the backend works with Vapi OR Bolna.

def bolna_authorised():
    """Accept the shared secret as a Bearer header (tool calls) or ?token= (post-call webhook,
    because Bolna's agent API cannot attach custom headers to the webhook)."""
    if not VAPI_WEBHOOK_SECRET:
        return True
    if request.headers.get("Authorization", "") == f"Bearer {VAPI_WEBHOOK_SECRET}":
        return True
    return request.args.get("token") == VAPI_WEBHOOK_SECRET


@app.post("/tools/<name>")
def bolna_tool(name):
    if not bolna_authorised():
        return jsonify({"error": "unauthorised"}), 401
    if name not in TOOLS:
        return jsonify({"result": f"Unknown tool {name}"}), 404
    args = request.get_json(silent=True) or {}
    args.update({k: v for k, v in request.args.items() if k not in args and k != "token"})
    call_id = args.pop("call_sid", None) or "bolna-call"
    try:
        return jsonify({"result": TOOLS[name](args, call_id)})
    except Exception as exc:  # never crash the live call
        app.logger.exception("tool failed")
        return jsonify({"result": f"Tool failed: {exc}. Apologise and offer a callback."})


# Bolna sends both "call-disconnected" and "completed" for one call; "completed" carries the
# transcript, summary and cost, so we store that one (plus the statuses where no call happened).
FINAL_STATUSES = ("completed", "no-answer", "busy", "failed",
                  "error", "canceled", "stopped", "balance-low")


def extracted_outcome(extracted):
    """Find our 'recovery_outcome' extraction anywhere in Bolna's extracted_data (backup signal)."""
    if not isinstance(extracted, dict):
        return None
    for category in extracted.values():
        if isinstance(category, dict):
            item = category.get("recovery_outcome")
            if isinstance(item, dict):
                return item.get("objective") or item.get("subjective")
            if isinstance(item, str):
                return item
    return None


@app.post("/bolna/webhook")
def bolna_webhook():
    """Bolna sends call status updates here. We save the final one (transcript, cost, recording)."""
    if not bolna_authorised():
        return jsonify({"error": "unauthorised"}), 401
    data = request.get_json(silent=True) or {}
    if data.get("status") in FINAL_STATUSES:
        telephony = data.get("telephony_data") or {}
        context = data.get("context_details") or {}
        recipient = context.get("recipient_data") or data.get("user_data") or {}
        cost_cents = data.get("total_cost")
        save_event({
            "type": "call_ended",
            "call_id": data.get("id"),
            "customer_id": recipient.get("customer_id"),
            "ended_reason": telephony.get("hangup_reason") or data.get("status"),
            "summary": data.get("summary"),
            "cost_usd": round(cost_cents / 100, 4) if isinstance(cost_cents, (int, float)) else None,
            "duration_sec": data.get("conversation_duration") or telephony.get("duration"),
            "recording_url": telephony.get("recording_url"),
            "voicemail": data.get("answered_by_voice_mail"),
            "extracted_outcome": extracted_outcome(data.get("extracted_data")),
            "transcript": data.get("transcript"),
        })
    return jsonify({"ok": True})


# ---------- dashboard ----------

def build_metrics():
    customers = load_customers()
    events = load_outcomes()

    # Latest outcome per customer
    latest = {}
    for e in events:
        if e["type"] == "outcome":
            latest[e["customer_id"]] = e

    # Check every payment link with Razorpay to see if it's actually been paid
    links = [e for e in events if e["type"] == "payment_link_sent"]
    paid_customers = set()
    for link in links:
        link["status"] = get_payment_link_status(link["link_id"])
        if link["status"] == "paid":
            paid_customers.add(link["customer_id"])

    # One row per call: keep the latest end-of-call event for each call id
    by_call = {}
    for e in events:
        if e["type"] == "call_ended":
            by_call[e.get("call_id") or id(e)] = e
    calls = list(by_call.values())
    total_cost = sum(c.get("cost_usd") or 0 for c in calls)

    # Backup signal: Bolna's post-call extraction, used only if the agent forgot to log an outcome
    extracted = {c["customer_id"]: c["extracted_outcome"] for c in calls
                 if c.get("customer_id") and c.get("extracted_outcome")}

    rows = []
    for cid, c in customers.items():
        o = latest.get(cid, {})
        source = "agent" if o else ""
        outcome = o.get("outcome")
        if not outcome and cid in extracted:
            outcome, source = extracted[cid], "extraction"
        if cid in paid_customers:
            outcome, source = "paid_via_link", "razorpay"
        if not outcome:
            outcome = "skipped_do_not_call" if c["do_not_call"] else "not_called"
        expected = c.get("expected_outcomes", [])
        if outcome == "not_called":
            check = ""
        else:
            check = "pass" if outcome in expected else "fail"
        rows.append({**c, "outcome": outcome, "source": source, "check": check,
                     "notes": o.get("notes", ""), "promise_date": o.get("promise_date")})

    tested = [r for r in rows if r["check"]]
    passed = [r for r in tested if r["check"] == "pass"]

    due = sum(c["amount_inr"] for c in customers.values() if not c["do_not_call"])
    recovered = sum(customers[cid]["amount_inr"] for cid in paid_customers)
    promised = sum(customers[r["customer_id"]]["amount_inr"]
                   for r in rows if r["outcome"] == "promise_to_pay")
    reached = len([r for r in rows if r["outcome"] not in ("not_called", "skipped_do_not_call")])

    return {
        "rows": rows,
        "links": links,
        "calls": calls,
        "due": due,
        "recovered": recovered,
        "promised": promised,
        "recovery_rate": round(100 * recovered / due, 1) if due else 0,
        "reached": reached,
        "total": len(customers),
        "scenarios_tested": len(tested),
        "scenarios_passed": len(passed),
        "total_cost_usd": round(total_cost, 2),
        "cost_per_recovered_rupee": round((total_cost * 84) / recovered, 3) if recovered else None,
        "generated_at": now_ist_str(),
    }


@app.get("/")
def dashboard():
    return render_template("dashboard.html", m=build_metrics())


@app.get("/api/metrics")
def metrics_api():
    return jsonify(build_metrics())


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
