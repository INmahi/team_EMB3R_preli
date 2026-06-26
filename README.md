# QueueStorm Investigator

An AI/API **support copilot** for a digital-finance platform, built for the bKash SUST CSE
Carnival 2026 Codex Community Hackathon (Online Preliminary). It receives one customer
complaint plus a snippet of the customer's recent transaction history and returns a single
structured JSON response that **classifies, routes, and explains** the case — acting as an
*investigator*, not just a classifier.

- `GET /health` → `{"status":"ok"}`
- `POST /analyze-ticket` → structured analysis (schema below)

## Tech stack

- **Python 3.12 + FastAPI + Uvicorn** — async HTTP service.
- **Pydantic v2** — enforces the exact request/response schema and enum values, giving the
  correct HTTP status codes (200/400/422) almost for free.
- **httpx** — used only by the optional LLM layer.
- No GPU, no baked model weights → small image, fast cold start.

## Architecture

```
app/
  main.py       FastAPI app: /health, /analyze-ticket, exception handlers (400/422/500)
  schemas.py    Pydantic models + exact enum taxonomy
  reasoning.py  Deterministic investigation engine (the core decision logic)
  keywords.py   Multilingual (en / bn / banglish) keyword maps
  safety.py     Safe-by-construction templates + a hard output sanitizer
  llm.py        OPTIONAL OpenAI-compatible LLM refinement (off by default)
  config.py     Env-only configuration
```

**Request flow:** parse & validate (Pydantic) → `investigate()` decides every field
deterministically → `compose()` builds safe text → *(optional)* LLM rewrites the wording →
**safety sanitizer always runs last** → response.

## AI approach (hybrid, deterministic-first)

The decision fields that carry the score — `relevant_transaction_id`, `evidence_verdict`,
`case_type`, `severity`, `department`, `human_review_required`, `reason_codes` — are produced
by a **deterministic rules engine**. This is fast (p95 ≪ 5s), free, reproducible, and immune
to prompt injection.

How the investigator reasons:
1. **Transaction matching** — scores each history entry against the complaint by amount,
   counterparty/phone, transaction type, status words, and an explicit transaction-id mention;
   picks the best match above a threshold, else `null`.
2. **Evidence verdict** — compares the matched transaction's `status`/`amount` against what the
   complaint claims: `consistent`, `inconsistent` (e.g. "payment failed" but status `completed`,
   or amount mismatch), or `insufficient_data` (empty/irrelevant history, or no match).
3. **Classification** — multilingual keyword + evidence scoring over the Section 7.1 taxonomy.
   **Phishing/social-engineering wins ties** so risky cases are never under-routed.
4. **Severity / routing / escalation** — derived from case type, amount, and verdict; department
   follows the Section 7.2 mapping; `human_review_required` is set for disputes, fraud, high-value,
   and any non-`consistent` (ambiguous) evidence.

An **optional LLM layer** (off by default) only *rewrites the wording* of `agent_summary` and
`customer_reply` for clarity and language match. It never changes decisions, runs with an 8s
timeout and silent deterministic fallback, and its output is always re-sanitized.

## Safety logic

Safety is enforced **structurally**, not hoped for:

- **Safe-by-construction templates** for `customer_reply` per case type: they never request
  PIN/OTP/password/card, never confirm a refund/reversal (they say *"any eligible amount will be
  returned through official channels after review"*), and direct customers to official channels only.
- **A hard sanitizer** (`safety.sanitize_text`) runs on **all** outgoing text — and is the safety
  net for any LLM output. It drops sentences that *ask* for secret credentials (while preserving
  *warnings* not to share them), softens definitive refund/reversal promises, and strips
  third-party/link redirects in favor of official-channel guidance.
- **Prompt-injection resistance** — the complaint is treated strictly as data; the deterministic
  engine cannot be instructed by it, and the LLM system prompt + sanitizer defend the optional path.

This maps directly to the Section 8 penalty rules (−15 credential requests, −10 unauthorized
confirmations, −10 third-party redirects).

## MODELS

| Model | Where it runs | Why / status |
|---|---|---|
| **None (default)** | In-process Python rules | The service ships **LLM-off**. All scored decisions and safe replies are produced deterministically — zero cost, zero external dependency, sub-second latency. |
| **Groq — `llama-3.3-70b-versatile`** *(suggested if LLM enabled)* | Groq cloud (OpenAI-compatible) | ~320 tok/s keeps us under the p95 ≤5s gate; free tier (30 RPM / 1,000 RPD). Used only to polish `agent_summary` + `customer_reply`. |
| **Google `gemini-2.0-flash`** *(alt)* | Google AI (OpenAI-compat endpoint) | Free 1,500 req/day; strongest Bangla/Banglish handling. |
| **OpenRouter `:free` models** *(alt)* | OpenRouter | One key, many free models; flexible fallback. |

The LLM is **pluggable via environment variables only** — switch providers with no code change.
**Cost reasoning:** default operation is free (rules only). If the LLM is enabled, only two short
text fields are sent per request to a free-tier provider, so expected cost is ~$0 within free limits;
on any quota/latency failure the service falls back to the free deterministic text.

## API

### `GET /health`
```json
{"status": "ok"}
```

### `POST /analyze-ticket`
Request and response schemas follow Problem Statement Sections 5–7. Example request:

```json
{
  "ticket_id": "TKT-001",
  "complaint": "I sent 5000 taka to a wrong number around 2pm today",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "campaign_context": "boishakh_bonanza_day_1",
  "transaction_history": [
    {"transaction_id": "TXN-9101", "timestamp": "2026-04-14T14:08:22Z",
     "type": "transfer", "amount": 5000, "counterparty": "+8801719876543",
     "status": "completed"}
  ]
}
```

A full worked input+output pair is in [`samples/sample_output.json`](samples/sample_output.json).

**Status codes:** `200` success · `400` malformed JSON / missing fields · `422` semantically
invalid (e.g. empty complaint) · `500` internal error (non-sensitive message, no stack traces).

## Setup & run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Unix: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then:
```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/analyze-ticket -H "Content-Type: application/json" -d @samples/sample_input.json
```

### Docker
```bash
docker build -t queuestorm .
docker run --rm -p 8000:8000 --env-file .env queuestorm
```

### Tests
```bash
pytest -q
```

Full deployment + judging instructions: see [RUNBOOK.md](RUNBOOK.md).

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Bind port (Railway injects this). |
| `LLM_ENABLED` | `false` | Turn the optional LLM polish on. |
| `LLM_BASE_URL` | Groq | Any OpenAI-compatible base URL. |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Model name. |
| `LLM_API_KEY` | *(empty)* | Provider key — set in the platform, never in the repo. |
| `LLM_TIMEOUT` | `8` | Seconds before falling back to deterministic text. |

See [`.env.example`](.env.example). **No real secrets are committed.**

## Assumptions

- All complaints/transactions are synthetic; no real integrations are performed.
- Money amounts are BDT. High-value ≥ 10,000; critical ≥ 50,000.
- Bangla and Banglish cues are covered by curated keyword sets (extendable in `keywords.py`).
- The optional LLM only refines wording; the deterministic engine is authoritative.

## Known limitations

- Keyword-based multilingual detection can miss rare phrasings; the LLM layer (when enabled)
  mitigates this, and unmatched cases fall back to `other` + `customer_support` safely.
- Transaction matching is heuristic; genuinely ambiguous cases are intentionally marked
  `insufficient_data` and escalated for human review rather than guessed.
- The public sample pack was not yet available at build time; thresholds are calibrated to the
  written spec and the worked example, and `tests/test_samples.py` can ingest the official pack
  when provided for further calibration.
