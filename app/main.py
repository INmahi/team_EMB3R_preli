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
from .llm import analyze as llm_analyze
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


def _clamp_conf(value, fallback: float) -> float:
    """Accept an LLM-provided confidence only if it's a valid 0..1 number."""
    if isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0:
        return round(float(value), 2)
    return fallback


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Must return {'status':'ok'} within 60s of start."""
    return {"status": "ok"}


@app.post("/analyze-ticket", response_model=TicketResponse)
def analyze_ticket(req: TicketRequest) -> TicketResponse:
    # Semantic validation -> 422 (schema was valid, content is not usable).
    if not req.complaint or not req.complaint.strip():
        raise HTTPException(status_code=422, detail="complaint must not be empty")

    # Deterministic investigation always runs: it is the baseline hint for the
    # LLM and the guaranteed-valid fallback if the LLM is off/slow/invalid.
    inv = investigate(req)
    agent_summary, next_action, customer_reply = compose(inv, req)

    # Build the deterministic response first.
    resp = TicketResponse(
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

    # Hybrid: if the LLM is enabled and returns a valid analysis, let it drive the
    # decision fields. Pydantic re-validates enums; on any failure we keep `resp`.
    data = llm_analyze(req, inv)
    if data:
        # Guardrail: when the rules matcher found a genuine tie, never let the LLM
        # guess a transaction — defer to the deterministic "don't guess" result.
        rid = data["relevant_transaction_id"]
        verdict = data["evidence_verdict"]
        if inv.ambiguous_match:
            rid = inv.relevant_transaction_id
            verdict = inv.evidence_verdict.value
        try:
            llm_resp = TicketResponse(
                ticket_id=inv.ticket_id,
                relevant_transaction_id=rid,
                evidence_verdict=verdict,
                case_type=data["case_type"],
                severity=data["severity"],
                department=data["department"],
                agent_summary=sanitize_text(data["agent_summary"]),
                recommended_next_action=sanitize_text(data["recommended_next_action"]),
                customer_reply=sanitize_text(data["customer_reply"]),
                # Safety guardrail: escalate if EITHER source flags review; never downgrade.
                human_review_required=bool(data["human_review_required"]) or inv.human_review_required,
                confidence=_clamp_conf(data.get("confidence"), inv.confidence),
                reason_codes=data.get("reason_codes") or inv.reason_codes,
            )
            resp = llm_resp
        except Exception:
            logger.warning("LLM output failed schema validation; using deterministic result")

    return resp


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
