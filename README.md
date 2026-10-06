# Asha: a voice agent that recovers failed autopay payments

Asha calls a subscription customer whose autopay failed, confirms who she is talking to, explains **why** the payment failed, and offers the fix that fits that reason. That might be a Razorpay payment link sent during the call, a promise-to-pay date, an automatic retry, or a hand-off to a human. Every outcome is logged and measured on a live dashboard.

Built for the Razorpay Forward-Deployed Engineer (Agent Studio) assignment, option 2.

> **Demo video:** _link added shortly_
> Shows two live calls to my own phone (a payment link sent and paid; a wrong person answering) and the dashboard updating.

---

## 1. The merchant problem, and why this is not a reminder bot

A failed autopay is not one problem. The right action depends on **why** it failed:

| Failure reason | What the customer needs | What Asha does |
|---|---|---|
| Low balance | A way to pay, now or later | Payment link now, or a promise-to-pay date (max 10 days) |
| Mandate paused or cancelled in the UPI app | To pay, and to set autopay up again, unless they cancelled on purpose | Asks first. Link if it was a mistake; one alternative, then accept, if on purpose |
| Card expired | To pay and save a new card | Link that lets them pay and save the new card |
| Bank technical decline | Nothing. It wasn't their fault | Reassures them, **does not ask for payment**, logs an automatic retry |
| "I already paid" | Not to be chased | Takes the UTR, logs it for reconciliation, no argument |
| "I never signed up" | A human, now | Stops payment talk, escalates to a specialist |

A generic "please pay" call damages the merchant relationship in at least three of these six cases.

## 2. How it works

```
 make_calls.py ──► Bolna (voice agent "Asha") ──► customer's phone
  (guardrails)        │  speech-to-text, LLM, voice
                      │
                      │  tool calls (HTTPS + shared secret)
                      ▼
                 app.py  (Flask backend)
                   ├─ verify_identity   → checks birth year against the record (the AI never sees it)
                   ├─ send_payment_link → creates a Razorpay Payment Link (test mode); blocked until verified
                   ├─ schedule_callback / escalate_to_human / log_outcome
                   └─ /bolna/webhook    → end-of-call transcript, cost, recording, outcome
                      │
                      ▼
                 Dashboard (localhost) → recovered ₹, recovery rate, pass/fail per scenario,
                                         payment status checked live with Razorpay
```

**Stack:** Bolna (voice platform; Deepgram nova-3 speech-to-text, GPT-4.1-mini, ElevenLabs voice, Vobiz telephony), Python/Flask backend, Razorpay Payment Links API (test mode), ngrok tunnel.

**Configuration as code:** the full Bolna agent (prompts, 5 tools, multilingual set-up, engine settings) is in `bolna_setup/agent_config.json`. It was created through the Bolna MCP server rather than by clicking through the dashboard, so the agent can be rebuilt exactly and reviewed in a diff.

## 3. Guardrails, and where each one is enforced

The rule I followed: **anything with money or privacy consequences is enforced in code, not left to the AI.**

| Guardrail | Enforced by |
|---|---|
| Identity check before any payment detail is shared | **Server.** `verify_identity` compares the year the caller said with the record. The real year is never in the AI's prompt |
| Lock after 2 wrong answers (even the right year is refused after that) | **Server** |
| No payment link without verification | **Server.** `send_payment_link` refuses unless verification succeeded in the last 15 minutes |
| No duplicate payment links | **Server.** Re-uses an unpaid link instead of creating a second |
| Correct amount spoken | **Server.** The amount is converted to English and Hindi words before the call (`amount_words.py`); the AI only reads them |
| Only "paid" if Razorpay says so | **Server.** The dashboard checks payment status with Razorpay; the AI cannot log "paid" |
| Do-not-call list, 9 AM to 7 PM calling hours, max 3 attempts | **Dialler** (`make_calls.py`) |
| Only ever dials my own number | **Dialler.** Fictional customers' numbers are never used |
| Never asks for card, CVV, OTP or UPI PIN; no threats or legal language; one alternative before accepting a cancellation | Prompt |
| Disputes and fraud claims go to a human | Prompt + `escalate_to_human` tool |
| Tool calls and webhooks authenticated | Shared secret on every request |

## 4. Evaluation

### Automated tests
`python test_webhook.py` runs 17 checks against the backend (18 when Razorpay test keys are present): identity rejection and lockout, link blocked before verification, duplicate-event handling, authentication, cost conversion, and dashboard scoring.

### Live calls
Each fictional customer has an **expected outcome** (`data/customers.json`). The dashboard marks every call pass or fail against it. I ran 12 live calls to my own phone and read Bolna's raw logs for each, not just the summaries.

| # | Scenario | Language | Expected | Result |
|---|---|---|---|---|
| CUST001 | Low balance → pays now | English | link sent | ✅ (tested on an earlier agent version; re-run in the demo video) |
| CUST002 | Low balance, salary on the 7th; **wrong birth year given first** | Hindi | promise to pay | ✅ wrong year rejected, nothing revealed, verified on retry |
| CUST003 | Paused autopay by mistake | English | link sent | ✅ |
| CUST004 | Card expired | English | link sent | ✅ |
| CUST005 | Bank technical decline | Hindi | auto retry, no payment ask | ❌ then ✅ (see below) |
| CUST006 | Says already paid, gives UTR | English | already-paid logged | ✅ |
| CUST007 | Cancelled on purpose | English | cancellation, no pushing | ✅ |
| CUST008 | Doesn't recognise the charge | Hindi | escalated to human | ✅ |
| CUST009 | Father answers | English | nothing revealed, callback booked | ✅ |
| CUST010 | On do-not-call list | — | never dialled | ✅ blocked by the dialler |

**Unplanned real-world test:** on CUST007, "nineteen ninety" was misheard as 1999. The server rejected it, Asha revealed nothing, asked again, and verified on the second answer.

### Failures found on live calls, and the fix for each

| What went wrong on a real call | Root cause (from raw logs) | Fix |
|---|---|---|
| A wrong birth year (1951 for 1991) was accepted and the amount revealed | The AI was comparing the year itself; इक्यानवे/इक्यावन sound alike on a phone line | Moved verification to the server; removed the real year from the prompt |
| Said ₹1,499 instead of ₹2,499 in Hindi | The AI converted the number to Hindi words wrongly | Server converts amounts to words; the AI reads them |
| Logged "promise to pay" before the customer agreed | The tool call was made in the same turn as the question | Prompt rule: ask, wait, then act |
| Switched to Hindi at the end of an English call | "चलो ठीक है" was misheard and auto-detection flipped language | Switch only on request; Hindi customers start in Hindi |
| Asked the birth-year question in both languages | One prompt contained both languages | A separate prompt per language, built from one template |
| Each call counted twice on the dashboard | Bolna sends two end-of-call events | Store one event per call |

**Cost:** about ₹10 (12 US cents) per 100-second call on the Bolna trial.

## 5. Setup and run

Requires Python 3.9+, a Razorpay account in **test mode**, a Bolna account (free trial credit is enough), and ngrok.

```bash
git clone <this repo> && cd autopay-recovery-agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in your keys (see comments inside)
python test_webhook.py        # needs the server running; see below
```

1. **Start the backend:** `python app.py` → dashboard at http://localhost:5050
2. **Expose it:** `ngrok http --url=<your-ngrok-domain> 5050`
3. **Create the agent:** create a Bolna agent from `bolna_setup/agent_config.json`. Replace `illusive-apple-sedative.ngrok-free.dev` with your domain and `${VAPI_WEBHOOK_SECRET}` with your secret. I used the Bolna MCP server's `create_agent`; the Bolna API `POST /v2/agent` takes the same body. Put the agent ID in `.env`.
4. **Verify your phone number in Bolna** (the trial only calls verified numbers).
5. **Call:** `python make_calls.py --customer CUST001` (add `--ignore-hours` outside 9 AM–7 PM). To pay the link in test mode, use UPI ID `success@razorpay`.

If you change the prompt, edit `prompts/system_prompt.md` and run `python bolna_setup/build_prompts.py` to regenerate the English and Hindi versions.

## 6. Repository map

| Path | What it is |
|---|---|
| `app.py` | Backend: the 5 tools, Bolna webhook, dashboard metrics |
| `make_calls.py` | Dialler with do-not-call, hours and attempt guardrails |
| `amount_words.py` | Rupee amounts → English and Hindi words |
| `prompts/system_prompt.md` | Prompt template (single source) → `system_prompt_en.md`, `system_prompt_hi.md` |
| `bolna_setup/agent_config.json` | Full Bolna agent config (secret removed) |
| `data/customers.json` | 10 fictional customers with expected outcomes |
| `templates/dashboard.html` | Outcomes dashboard |
| `test_webhook.py` | Backend tests |
| `setup_vapi.py`, `diagnose_call.py` | First attempt on Vapi + Twilio (see below). Not used in the demo |
| `MERCHANT_MEMO.md` | One-page business case for a merchant |

## 7. Assumptions

- All customers, amounts and merchants are fictional. Every call went to my own verified number.
- Birth year stands in for the merchant's real verification method.
- "Recovered" means Razorpay reports the payment link as paid. A customer saying "I've paid" does not count.
- Callbacks and escalations are recorded for a human team to act on; they are not scheduled automatically.

## 8. Limitations, stated plainly

- **The agent does not hang up by itself.** Bolna's prompt-based hang-up never ran on API-created agents across 12 calls (the usage report shows the hang-up check as null every time). Calls end 6 seconds after the goodbye through the silence timeout. I'd raise this with Bolna rather than work around it further.
- **Runs on a laptop.** The backend runs locally behind ngrok and stores events in a JSON file.
- **SMS not delivered in test mode.** Razorpay test mode creates real payment links but doesn't send real SMS, so the demo opens the link from the dashboard.
- **Birth year is weak authentication.** Fine for a demo; not for production.
- **Payment status is polled**, not received through Razorpay webhooks.
- **Shared trial caller ID.** A real deployment needs the merchant's registered number under Indian telecom rules.
- **Transcription of Indian names and numbers is imperfect.** The design is built to fail safe (reject and re-ask), not to assume perfect hearing.

## 9. What production would need

1. Deploy the backend to a cloud service; Postgres instead of a JSON file; a proper secret store.
2. Razorpay **webhooks** for payment and subscription events, triggering calls automatically when a mandate fails.
3. Stronger verification (registered phone number + last 4 digits of the mandate account, or OTP over SMS handled outside the call).
4. A callback scheduler and a human queue (e.g. a ticket created per escalation).
5. Per-merchant calling windows, frequency caps, and the merchant's own caller ID.
6. A regression suite: replay recorded transcripts against new prompt versions before each release.
7. A pilot plan; see `MERCHANT_MEMO.md`.

## 10. Why Bolna, not Vapi + Twilio

I started on Vapi with a Twilio number. Twilio trial accounts can't place international calls or use custom call instructions, so Vapi's calls to Indian numbers failed (`call.start.error-get-transport`). I wrote `diagnose_call.py` to test Twilio directly, confirmed the trial restriction, and moved to Bolna, which calls Indian numbers on its free tier. The backend supports both providers (`VOICE_PROVIDER` in `.env`).
