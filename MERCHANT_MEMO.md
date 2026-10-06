# Merchant memo: recovering failed autopay with a voice agent

**For:** a subscription merchant on Razorpay (for example, a streaming, fitness or SaaS business)
**From:** Aditya Mathur, Forward-Deployed Engineer (assignment)

## The problem
Every month some autopay debits fail: low balance, a mandate paused in a UPI app, an expired card, or a bank-side error. Today most merchants either retry blindly or send a generic SMS. Both ignore **why** the payment failed, so they recover little and annoy customers who did nothing wrong.

## What we would deploy
A voice agent that calls only the customers worth calling, in their language (English or Hindi), and handles each failure reason differently. It sends a Razorpay payment link during the call when that helps, books a promise-to-pay date when it doesn't, and hands disputes to a human. Every call ends with a logged outcome.

## How to size the value (fill in with your numbers)

| Input | Your value | Illustrative example |
|---|---|---|
| Active subscribers on autopay | A | 50,000 |
| Monthly autopay failure rate | B | 5% |
| Share of failures worth calling (not bank errors or do-not-call) | C | 70% |
| Average monthly charge | D | ₹699 |
| Extra recovery from calling vs. today's process | E | 15 percentage points |

**Extra monthly revenue recovered = A × B × C × E × D**
Example: 50,000 × 5% × 70% × 15% × ₹699 ≈ **₹1.8 lakh per month**, plus the customers kept rather than lost to churn.

**Call cost:** about ₹10 per 100-second call in testing. At the example volume (1,750 calls per month), that is about **₹17,500 per month**, roughly one-tenth of the example recovery.

_The example numbers are illustrative assumptions, not benchmarks. The pilot exists to measure E._

## Pilot design (4 weeks)
1. **Split:** randomly assign failed-autopay customers to "voice agent" or "current process" (holdout).
2. **Measure:** recovery rate (paid within 7 days), revenue recovered, promises kept, cost per rupee recovered, complaints, opt-outs, and escalations.
3. **Guardrails during the pilot:** calls 9 AM to 7 PM only, at most 3 attempts per customer, do-not-call respected, every dispute goes to a human, weekly review of a sample of call recordings.
4. **Decision rule:** expand if the voice group recovers clearly more than the holdout at a cost per rupee recovered the merchant accepts, with no rise in complaints.

## What the merchant needs to provide
Failed-payment events (via Razorpay webhooks), customer language preference, a registered caller ID, the verification method they already trust, and a human team or queue for escalations and callbacks.
