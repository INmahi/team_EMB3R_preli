# CLAUDE.md

Guidance for working in this repository.

> **Status:** The official **Problem Statement is NOT yet provided.** It defines the
> exact input/output JSON schema, enum values, and the main endpoint name. Until it
> arrives, treat all schema details below as *placeholders* and confirm against the
> problem statement before implementing. The two source documents that drive this
> project are [SUST_CSE_Carnival_2026_Team_Instructions.md](SUST_CSE_Carnival_2026_Team_Instructions.md)
> and [sust_cse_carnival_2026_rubric.md](sust_cse_carnival_2026_rubric.md).

## What we are building

**bKash / SUST CSE Carnival 2026 — Codex Community Hackathon, AI/API 4-Hour Online Preliminary.**

A backend **API service** acting as a **support copilot**: it receives a case (customer
support ticket + evidence/context) and returns a structured decision. It must reason
from supplied evidence (not keyword-match), behave safely, and escalate uncertain or
risky cases to human review.

- **Frontend/UI is NOT required and NOT judged.** Spend zero time on UI.
- The judge is an **automated harness** that calls the deployed endpoints directly —
  no login, dashboard, manual approval, or private network allowed.

## Required endpoints (hard contract)

| Endpoint | Requirement |
| --- | --- |
| `GET /health` | Must return exactly `{"status":"ok"}`. Must respond within 60s of service start. |
| `POST /analyze-ticket` | **Confirmed route name** (from submission instructions). Accepts the required input JSON, returns the required structured output JSON. Must complete within 30s per request. |

- Always return `application/json`. No extra logs/text in the response body.
- Bind to `0.0.0.0` on the documented port (default `PORT=8000`).
- Use the **exact** field names, types, and enum values from the Problem Statement.

## Scoring priorities (from the rubric — build in this order)

1. **API Contract & Schema (15)** — get endpoints + exact JSON shape/enums/status codes right first; nothing scores if the shape is wrong.
2. **Evidence Reasoning (35)** — the biggest score. Decide from the supplied case evidence, identify relevant evidence, pick the right review outcome, route/escalate correctly.
3. **Safety & Escalation (20)** — hard requirement; see penalties below. Add guardrails before polishing text.
4. **Performance & Reliability (10)** — p95 latency ≤5s for full credit (partial to 15s, minimal to 30s); no 5xx/invalid JSON on valid input; handle malformed/missing fields without crashing.
5. **Response Quality (10)** — clear summary, practical next action, professional customer reply (manual review, shortlisted teams only).
6. **Deployment & Reproducibility (5)** — reachable endpoint or clean Docker fallback, no manual debugging needed.
7. **Documentation (5)** — README (manual review, shortlisted teams only).

Stage 1 (automated, all teams): schema, evidence reasoning, safety, performance, reachability.
Stage 2 (manual, shortlisted only): response quality, documentation, originality.

## Safety rules (penalties are severe — never violate)

- **Never** ask for PIN, OTP, password, or secret credentials (−15). May *warn* users not to share these, but must never request them.
- **Never** promise/perform unauthorized actions, irreversible actions, account changes, or guaranteed outcomes (−10). It can *recommend* a review, not promise direct action.
- **Never** tell the customer to contact suspicious third parties — only official support channels (−10).
- **Two or more critical safety violations → disqualified** from the top-40 pool.
- When uncertain or risky → **escalate to human review** rather than guessing confidently.
- Tie-breaker #1 is safety, so prefer safe-and-correct over confident-and-risky.

## AI / model policy

- **Hybrid rule + AI is recommended:** deterministic logic for validation/safety, AI for language understanding / structured reasoning / drafting.
- Rule-based-only is explicitly allowed and encouraged — task is solvable without paid APIs.
- External AI APIs (OpenAI, Anthropic, etc.) allowed with the **team's own keys**; team owns cost/quota/rate-limits/availability during evaluation.
- Lightweight local models OK only if CPU-only and within image/runtime limits.
- **No GPU, no huge LLMs, no multi-GB downloads at eval time, no runtime training.**
- Build robust fallbacks for external-API failure (quota/rate-limit) → return a controlled safe response, never crash.

## Secrets

- **Never commit real secrets** (not in code, README, screenshots, Docker image, or commit history) — even in a private repo.
- Repo contains only source, README, deps, Dockerfile, and **`.env.example`** (variable names + placeholder values only).
- Real secrets live in the hosting platform's env vars (deployed path) or the submission form's private field (Docker/code fallback only).
- Expected env vars: `OPENAI_API_KEY`, `MODEL_NAME`, `PORT` (placeholders for now).
- Never leak keys, tokens, or stack traces in logs or responses.

## Deployment (preference order)

1. **Public endpoint URL** + GitHub repo (preferred — judges call the API directly).
2. **Docker fallback** — image <500MB recommended, **1GB hard limit**, no GPU, no large weights, binds `0.0.0.0`, `/health` ready within 60s, secrets via env only.
   ```bash
   docker build -t hackathon-team .
   docker run -p 8000:8000 --env-file judging.env hackathon-team
   ```
3. **Code-only** with full setup/run docs (last resort, reduced credit).

## README must cover (required deliverable)

Setup, run command, sample request + sample response, AI/model usage (rules/local/external/hybrid),
safety logic (sensitive-data, authorization, unsafe-action safeguards), and known limitations.

## Pre-submission checklist

- [ ] Implementation matches the Problem Statement schema exactly (fields, types, enums, status codes).
- [ ] `GET /health` returns `{"status":"ok"}`; `POST` main endpoint tested with sample JSON.
- [ ] Handles empty/missing optional fields and malformed input without crashing.
- [ ] Safety guardrails tested (no credential requests, no unauthorized promises, official channels only).
- [ ] Responds within timeout; stays reachable during the eval window.
- [ ] Endpoint deployed OR Docker/code fallback prepared.
- [ ] Repo accessible to organizers (add organizer GitHub handle if private); no real secrets committed.
- [ ] `.env.example` present; README complete; only synthetic data used.

## Submission

- **GitHub:** https://github.com/INmahi/team_EMB3R_preli.git (git initialized, `origin` wired).
- **Organizer handle:** add **`bipulhf`** with **read** access if the repo is private (before deadline).
- **Submission path:** public endpoint preferred → Railway URL. Docker fallback second; code-only last.
- **Host:** Railway (signed in, repo connected). No EC2/Poridhi VM needed.
- **Hard deadline rule:** you **cannot commit/push after the deadline** — push final code well before.
- **Required before submit:** `/health` + `/analyze-ticket` live · README (setup, run, AI/model usage, safety logic, limitations) · organizer has repo access · no real secrets / no real customer/payment data committed.
