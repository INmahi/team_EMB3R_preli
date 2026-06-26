"""FastAPI application: GET /health and POST /analyze-ticket.

Implements the API contract (Section 4) including the HTTP status-code semantics:
  200 success | 400 malformed/missing fields | 422 semantically invalid | 500 internal.
The service is built to never crash on bad input and never leak secrets/stack traces.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import settings
from .llm import refine
from .reasoning import investigate
from .safety import compose, sanitize_text
from .schemas import TicketRequest, TicketResponse

logger = logging.getLogger("queuestorm")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="QueueStorm Investigator",
    description="AI/API support copilot — classifies, routes, and explains finance complaints.",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Must return {'status':'ok'} within 60s of start."""
    return {"status": "ok"}


@app.post("/analyze-ticket", response_model=TicketResponse)
def analyze_ticket(req: TicketRequest) -> TicketResponse:
    # Semantic validation -> 422 (schema was valid, content is not usable).
    if not req.complaint or not req.complaint.strip():
        raise HTTPException(status_code=422, detail="complaint must not be empty")

    # Deterministic investigation (the authoritative decision).
    inv = investigate(req)
    agent_summary, next_action, customer_reply = compose(inv, req)

    # Optional LLM polish (no-op unless configured); always re-sanitized.
    refined = refine(inv, req, agent_summary, customer_reply)
    if refined:
        agent_summary = sanitize_text(refined["agent_summary"])
        customer_reply = sanitize_text(refined["customer_reply"])

    return TicketResponse(
        ticket_id=inv.ticket_id,
        relevant_transaction_id=inv.relevant_transaction_id,
        evidence_verdict=inv.evidence_verdict,
        case_type=inv.case_type,
        severity=inv.severity,
        department=inv.department,
        agent_summary=agent_summary,
        recommended_next_action=next_action,
        customer_reply=customer_reply,
        human_review_required=inv.human_review_required,
        confidence=inv.confidence,
        reason_codes=inv.reason_codes,
    )


# --------------------------------------------------------------------------- #
# Exception handlers — map to the required status codes, never leak internals. #
# --------------------------------------------------------------------------- #
@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Malformed JSON or missing/invalid required fields -> 400 per Section 4.1.
    return JSONResponse(
        status_code=400,
        content={"error": "malformed_request", "detail": "Invalid or missing request fields."},
    )


@app.exception_handler(HTTPException)
async def on_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "request_error", "detail": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def on_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Never expose stack traces, tokens, or secrets in the response body.
    logger.exception("Unhandled error processing request")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "detail": "An internal error occurred."},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
