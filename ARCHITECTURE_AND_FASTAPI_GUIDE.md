# QueueStorm Investigator — Architecture & FastAPI Learning Guide

> A from-scratch, beginner-friendly walkthrough of how this project works **and** how
> FastAPI works in general. Read top to bottom; every concept is explained the first
> time it appears, using this project's real code as the example.
>
> *(This file is intentionally untracked — it's a learning doc, not part of the submission.)*

---

## Part 0 — The mental model (read this first)

### What is a "backend API"?
Imagine a restaurant:
- **The customer** = some program (here, the judge's test harness) that wants something.
- **The waiter** = your **API**. It takes a written order, carries it to the kitchen, and brings back a plated dish.
- **The kitchen** = your business logic (the reasoning engine, the LLM, the safety rules).

The customer never walks into the kitchen. They only ever talk to the waiter, using a fixed
"menu" (the **API contract**: which URLs exist, what JSON to send, what JSON comes back).

Our menu has exactly two items:
| Method | URL | What it does |
|---|---|---|
| `GET` | `/health` | "Are you open?" → `{"status":"ok"}` |
| `POST` | `/analyze-ticket` | "Here's a complaint, analyze it" → a structured JSON verdict |

### What is HTTP, GET, POST, JSON?
- **HTTP** = the language browsers/servers speak. A client sends a **request**, the server sends a **response**.
- **GET** = "give me something" (no body needed). Used for `/health`.
- **POST** = "here's some data, do something with it" (has a **body**). Used for `/analyze-ticket`.
- **JSON** = a text format for structured data: `{"key": "value", "number": 5, "list": [1,2]}`.
  Both the request body and the response are JSON.
- **Status code** = a number describing the outcome: `200` OK, `400` bad request, `422` unprocessable, `500` server error.

### What is FastAPI?
**FastAPI** is a Python library for building APIs. You write normal Python **functions**, decorate
them with the URL they handle, and FastAPI does the tedious parts for you:
- reads the incoming HTTP request,
- converts the JSON body into Python objects **and validates it**,
- runs your function,
- converts your returned Python object back into JSON,
- sends the response with the right status code.

It sits on top of two lower-level pieces:
- **Starlette** — the web toolkit (routing, requests, responses).
- **Pydantic** — data validation using Python type hints (more on this soon).

And it's *run* by a server program called **Uvicorn** (explained in Part 6).

---

## Part 1 — The project at a glance

```
app/
  main.py       ← FastAPI app: defines the 2 endpoints + error handling   (the "waiter")
  schemas.py    ← Pydantic models: the exact shape of input/output JSON    (the "menu/forms")
  reasoning.py  ← Deterministic engine: rules that decide the answer        (a "kitchen station")
  keywords.py   ← Multilingual word lists used by reasoning.py
  safety.py     ← Safe reply templates + a sanitizer that scrubs output     (the "food safety inspector")
  llm.py        ← Calls an LLM to do the analysis (optional, primary brain) (the "head chef")
  config.py     ← Reads settings from environment variables
tests/          ← Automated tests that prove each part works
scripts/        ← Helper scripts (generate samples, evaluate, etc.)
Dockerfile      ← Recipe to package the app into a container
requirements.txt← The Python libraries we depend on
```

**One-line summary of the flow:** a request comes into `main.py` → it's validated by `schemas.py`
→ `reasoning.py` computes a safe baseline → `llm.py` (if enabled) produces the real answer →
`safety.py` scrubs the text → `main.py` returns JSON.

---

## Part 2 — FastAPI basics, using `main.py`

Here is the heart of the app (simplified from [app/main.py](app/main.py)):

```python
from fastapi import FastAPI, HTTPException
from .schemas import TicketRequest, TicketResponse

app = FastAPI()                      # 1. create the application

@app.get("/health")                  # 2. register a GET endpoint at /health
def health() -> dict[str, str]:
    return {"status": "ok"}          # 3. returning a dict -> FastAPI sends it as JSON

@app.post("/analyze-ticket", response_model=TicketResponse)
def analyze_ticket(req: TicketRequest) -> TicketResponse:
    ...
    return TicketResponse(...)
```

Let's unpack every line, because this tiny block contains 80% of FastAPI.

### `app = FastAPI()`
Creates the application object. Everything attaches to `app`. When Uvicorn runs your program, it
looks for this object (we point it there with `app.main:app` — meaning "in the `app/main.py` file,
use the variable named `app`").

### `@app.get("/health")` — a "decorator"
A **decorator** (the `@something` line above a function) attaches extra behavior to a function.
Here it tells FastAPI: *"when an HTTP `GET` arrives at the path `/health`, call this function."*
- `@app.get(...)` → handles GET requests.
- `@app.post(...)` → handles POST requests.

The function name (`health`) doesn't matter to HTTP — only the path in the decorator does.

### Returning a `dict` → automatic JSON
`return {"status": "ok"}` — FastAPI automatically converts the Python dictionary into the JSON
text `{"status":"ok"}` and sets `Content-Type: application/json`. You never manually build JSON.

### The magic line: `def analyze_ticket(req: TicketRequest)`
This is the part beginners find surprising. The **type hint** `req: TicketRequest` does a LOT:

1. FastAPI sees the parameter is a Pydantic model (`TicketRequest`), so it knows this endpoint
   expects a **JSON request body**.
2. It reads the incoming JSON, and tries to build a `TicketRequest` object from it.
3. If the JSON is missing required fields or has wrong types, FastAPI **automatically rejects it**
   with a validation error — your function never even runs.
4. If it's valid, your function receives a fully-typed Python object `req`, and you can write
   `req.complaint`, `req.transaction_history`, etc. with autocomplete.

So **validation is free** — you describe the shape once (in `schemas.py`) and FastAPI enforces it.

### `response_model=TicketResponse`
This tells FastAPI the shape of the **response**. It validates what you return, strips any extra
fields, and (bonus) documents the endpoint. If you tried to return something that doesn't match
`TicketResponse`, you'd get an error during development — catching bugs early.

---

## Part 3 — Pydantic: describing data with `schemas.py`

[app/schemas.py](app/schemas.py) defines the **exact shape** of our JSON. This is where the API
"contract" lives. Two key ideas: **models** and **enums**.

### Models = a form with typed fields
```python
from pydantic import BaseModel
from typing import Optional

class TicketRequest(BaseModel):
    ticket_id: str                       # required string
    complaint: str                       # required string
    language: Optional[str] = None       # optional (can be missing/null)
    transaction_history: list[TransactionEntry] = []   # a list of nested models
```
- Inheriting from `BaseModel` makes it a Pydantic model — Pydantic now validates any data you feed it.
- `ticket_id: str` means "this field is required and must be a string." Send a number → Pydantic
  tries to coerce or rejects it.
- `Optional[str] = None` means "may be absent; defaults to `None`."
- `list[TransactionEntry]` means "a list, where each item is itself a `TransactionEntry` model" —
  models can nest.

**Why this matters for the contest:** the judge scores you on returning the *exact* field names,
types, and enum values. By declaring them once here, Pydantic guarantees we never accidentally
return a wrong type or a typo'd field.

### Enums = "only these exact values are allowed"
```python
from enum import Enum

class EvidenceVerdict(str, Enum):
    consistent = "consistent"
    inconsistent = "inconsistent"
    insufficient_data = "insufficient_data"
```
An **enum** is a fixed set of allowed values. By typing a response field as `EvidenceVerdict`,
it's impossible to return `"Consistent"` or `"consistnet"` — only the three exact strings. This is
exactly what the rubric demands ("variants will be scored as schema violations").

### The two HTTP error codes you get "for free"
- If the body is missing `ticket_id` or `complaint`, Pydantic raises a validation error →
  we map it to **400**.
- If the body is well-formed but semantically wrong (e.g. `complaint` is just spaces), we raise
  it ourselves → **422**.

---

## Part 4 — The request's full journey (step by step)

Let's trace ONE real call: `POST /analyze-ticket` with a complaint + transaction history.

```
        ┌─────────────────────────── main.py: analyze_ticket() ───────────────────────────┐
JSON ──►│ 1. Pydantic builds TicketRequest (or 400/422 if invalid)                          │
        │ 2. Quick semantic check: empty complaint? -> raise 422                            │
        │ 3. investigate(req)         [reasoning.py] -> deterministic baseline answer        │
        │ 4. compose(inv, req)        [safety.py]    -> safe summary/action/reply (templates)│
        │ 5. llm_analyze(req, inv)    [llm.py]       -> LLM's own full answer (or None)       │
        │ 6. if LLM answered: use its decisions, BUT apply guardrails:                       │
        │       - ambiguity veto, hallucination check, human_review escalation               │
        │       - sanitize_text() on all text fields                                         │
        │ 7. build TicketResponse  -> FastAPI serializes to JSON -> 200                       │
        └───────────────────────────────────────────────────────────────────────────────────┘
```

The actual code (condensed from [app/main.py](app/main.py)):
```python
@app.post("/analyze-ticket", response_model=TicketResponse)
def analyze_ticket(req: TicketRequest) -> TicketResponse:
    if not req.complaint or not req.complaint.strip():
        raise HTTPException(status_code=422, detail="complaint must not be empty")

    inv = investigate(req)                          # deterministic baseline (always)
    agent_summary, next_action, customer_reply = compose(inv, req)

    resp = TicketResponse(...)                       # build the deterministic response

    data = llm_analyze(req, inv)                      # ask the LLM (None if disabled/failed)
    if data:
        # LLM's decisions win, but guardrails apply (ambiguity veto, sanitize, etc.)
        resp = TicketResponse(... sanitize_text(data["customer_reply"]) ...)

    return resp
```

**Key idea:** the deterministic answer is computed *first and always*, so there is ALWAYS a valid,
safe response ready. The LLM then *upgrades* it if it's available and its output passes the checks.
This is why the service can never "break" from an LLM failure — it just falls back.

---

## Part 5 — The four "kitchen stations" explained

### 5a. `reasoning.py` — the deterministic engine
Pure Python rules (no AI). Given the complaint + transactions it decides:
`relevant_transaction_id`, `evidence_verdict`, `case_type`, `severity`, `department`,
`human_review_required`. It's fast, free, and predictable. In the system it plays three roles:
the **fallback**, the **grounding hint** for the LLM, and the **guardrail** (e.g. it can detect
that a match is ambiguous and stop the LLM from guessing). You don't need to master its internals
to learn FastAPI — just know it's a normal Python function `investigate(req) -> Investigation`.

### 5b. `keywords.py` — multilingual word lists
Plain Python dictionaries/lists of phrases in English, Bangla, and "Banglish," used by
`reasoning.py` to spot what a complaint is about. No framework magic — just data.

### 5c. `safety.py` — the safety inspector
Two jobs:
1. **Templates**: ready-made safe replies per case type (never ask for PIN/OTP, never promise a
   refund, always point to official channels).
2. **`sanitize_text()`**: a function that scans ANY text (especially LLM output) and removes unsafe
   sentences. This is the last thing that touches the reply before it goes out, so even if the LLM
   misbehaves, the customer never sees a credential request or a refund promise.

### 5d. `llm.py` — the optional "head chef" (the AI brain)
This is where the project talks to a real LLM. Worth understanding in detail since you're learning.

```python
import httpx                       # an HTTP client (like 'requests', but modern)

def analyze(req, baseline):
    if not settings.llm_active():  # only if LLM_ENABLED=true AND a key is set
        return None
    ...
    with httpx.Client(timeout=settings.LLM_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)   # call the LLM provider
        data = json.loads(resp.json()["choices"][0]["message"]["content"])
    return _validate(data, req)    # reject bad enums / hallucinated transaction ids
```

Three things to notice:
- **`httpx`** lets our server act as a *client* to another server (the LLM provider, e.g. Groq).
  Same HTTP concepts, just the other direction.
- **`_validate(...)`** never trusts the LLM blindly: it checks the returned values are valid enums
  and that any transaction id actually exists in the input. If not → return `None` → fall back.
- **A hard timeout** wraps the call (using a thread with a deadline) so a slow provider can never
  make us exceed the 30-second response limit. On timeout → `None` → fall back.

---

## Part 6 — How the app actually runs: Uvicorn, ASGI, sync vs async

### Uvicorn is the engine; FastAPI is the car
FastAPI **describes** what to do with requests, but something has to actually open a network port,
listen for connections, and feed requests to FastAPI. That something is **Uvicorn** — an **ASGI
server**.

You start it like:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- `app.main:app` = "import the `app` object from `app/main.py`".
- `--host 0.0.0.0` = listen on all network interfaces (so it's reachable from outside the machine —
  important inside Docker/Railway, where `127.0.0.1` would be invisible to the outside).
- `--port 8000` = the port number clients connect to.

**ASGI** is just the modern Python standard for async-capable web servers. You don't write ASGI
directly; FastAPI speaks it for you.

### `def` vs `async def` (and why our endpoints are `def`)
FastAPI lets you write endpoints two ways:
- `async def` — for code that "awaits" other async operations (advanced).
- `def` (plain) — FastAPI runs these in a **threadpool** so they don't block the server.

Our `analyze_ticket` is a plain `def`. That choice matters for concurrency (next part).

---

## Part 7 — Concurrency: how it serves many requests at once

A common beginner worry: "if 10 requests arrive together, do they wait in line?"

**No.** Because our endpoint is a plain `def`, FastAPI/Starlette runs each call in a **threadpool**
(≈40 worker threads by default). So ~40 requests can be *in progress simultaneously*. While one
request is waiting ~1.2s for the LLM to reply, the other threads keep serving other requests.

Real measurement from the live service: **12 simultaneous requests all returned `200` in ~1.2s each,
finishing in ~1.3s total** (not 15s) — proof they ran in parallel, not one-by-one.

What happens under extreme load?
- Beyond ~40 truly-simultaneous requests, extras **queue** briefly (still served, just wait).
- If the free LLM hits its rate limit, those calls get rejected by the provider → our code
  **falls back to the instant deterministic engine**. So heavy bursts *degrade to fast rules*
  rather than failing. The fallback doubles as overload protection.

> Vocabulary: this is **vertical concurrency** (one process, many threads). "Horizontal load
> balancing" (many copies of the app behind a balancer) is a separate, bigger-scale technique we
> didn't need for a single judged service.

---

## Part 8 — Configuration & secrets: `config.py` + environment variables

Never hard-code secrets (API keys) in source. Instead the app reads them from **environment
variables** at startup ([app/config.py](app/config.py)):

```python
import os
class Settings:
    PORT = int(os.getenv("PORT", "8000"))          # use env PORT, else default 8000
    LLM_ENABLED = os.getenv("LLM_ENABLED") == "true"
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
```
- `os.getenv("NAME", default)` reads an environment variable.
- Locally you put these in a `.env` file (which is git-ignored). In production (Railway) you set
  them in the dashboard. The same code works everywhere without changes — and no secret is ever
  committed to git.

This is a core professional habit: **config comes from the environment, not the code.**

---

## Part 9 — Packaging & deployment (Docker + Railway), briefly

- **Dockerfile** = a recipe that builds a self-contained image: "start from Python 3.12, install
  `requirements.txt`, copy the `app/` folder, run uvicorn on `0.0.0.0:$PORT`." Anyone can run that
  image and get the identical service — no "works on my machine" problems.
- **Railway** = a hosting platform. It builds the Docker image from your GitHub repo and runs it,
  giving you a public HTTPS URL. It injects the `PORT` env var, which is why our code reads `$PORT`
  instead of hard-coding 8000.
- **GitHub Actions** = automation that rebuilds and publishes the Docker image on every push, so a
  downloadable image is always available as a backup.

---

## Part 10 — Testing (why and how)

[tests/](tests/) contains automated tests run with `pytest`. FastAPI provides a `TestClient` that
calls your endpoints **in-memory** (no real network needed):

```python
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```
- `client.get(...)` / `client.post(...)` simulate real HTTP calls.
- `assert` statements check the result; if any fails, the test fails.
- We have 40 tests covering schema validation, reasoning, safety, the LLM guardrails, and all 10
  public sample cases. Running `pytest -q` proves nothing broke after a change.

---

## Part 11 — Try it yourself (learning exercises)

1. **See auto-docs:** run `uvicorn app.main:app --reload`, then open `http://localhost:8000/docs`
   in a browser. FastAPI auto-generates an interactive API page from your type hints — try calling
   the endpoints there.
2. **Break validation on purpose:** POST `{}` (empty body) and watch it return 400. Add a typo to
   an enum in a response and watch Pydantic complain.
3. **Add a tiny endpoint:** add `@app.get("/ping")` returning `{"pong": True}`, restart, and curl it.
4. **Read one function end to end:** open `investigate()` in `reasoning.py` and follow how it turns
   a complaint into a decision.

---

## Glossary (quick reference)

| Term | Meaning |
|---|---|
| **API** | A defined way for programs to talk over HTTP. |
| **Endpoint / route** | A specific URL + method your API handles (e.g. `POST /analyze-ticket`). |
| **HTTP method** | `GET` (fetch), `POST` (send data), etc. |
| **Status code** | Result number: 200 ok, 400/422 client error, 500 server error. |
| **JSON** | Text format for structured data. |
| **FastAPI** | Python framework for building APIs from typed functions. |
| **Pydantic** | Validates data using Python type hints (the `BaseModel` classes). |
| **Model** | A Pydantic class describing the shape of some data. |
| **Enum** | A fixed set of allowed values. |
| **Decorator** | `@app.get(...)` — attaches routing behavior to a function. |
| **Type hint** | `req: TicketRequest` — tells Python/FastAPI the expected type. |
| **Uvicorn** | The ASGI server that actually runs the app. |
| **ASGI** | The async server standard FastAPI uses. |
| **Threadpool** | Pool of worker threads that lets many `def` endpoints run at once. |
| **Environment variable** | A setting read from the OS/host (`os.getenv`), used for secrets/config. |
| **Docker image** | A packaged, runnable snapshot of the app + its dependencies. |
| **httpx** | HTTP client library used to call the LLM provider. |
| **Fallback** | Using the deterministic result when the LLM is unavailable/invalid. |

---

### TL;DR
A request hits **Uvicorn**, which hands it to **FastAPI** (`main.py`). **Pydantic** (`schemas.py`)
validates the JSON into a Python object. The **deterministic engine** (`reasoning.py`) computes a
guaranteed-safe baseline; the **LLM** (`llm.py`) then produces the real answer if available;
**safety** (`safety.py`) scrubs the text; FastAPI serializes the result back to JSON. Many requests
run at once via the **threadpool**, secrets come from **environment variables**, and the whole thing
ships as a **Docker image** on **Railway**.
