"""Tests for the optional LLM layer: validation, fallback, and safety guardrail.

These run without any network/key — they exercise the validator and the orchestration
fallback path directly.
"""
from app import llm
from app.reasoning import investigate
from app.schemas import TicketRequest, TransactionEntry


def _req():
    return TicketRequest(
        ticket_id="TKT-001",
        complaint="I sent 5000 taka to a wrong number",
        transaction_history=[
            TransactionEntry(transaction_id="TXN-9101", type="transfer", amount=5000,
                             counterparty="+8801719876543", status="completed")
        ],
    )


def test_analyze_returns_none_when_llm_disabled():
    # Default config has LLM_ENABLED=false -> no key -> must no-op.
    assert llm.analyze(_req(), investigate(_req())) is None


def test_validate_rejects_bad_enum():
    req = _req()
    bad = {
        "relevant_transaction_id": "TXN-9101", "evidence_verdict": "consistent",
        "case_type": "WRONG_TRANSFER",  # wrong case -> invalid enum
        "severity": "high", "department": "dispute_resolution",
        "agent_summary": "x", "recommended_next_action": "y", "customer_reply": "z",
        "human_review_required": True, "confidence": 0.9, "reason_codes": [],
    }
    assert llm._validate(bad, req) is None


def test_validate_rejects_hallucinated_transaction_id():
    req = _req()
    bad = {
        "relevant_transaction_id": "TXN-DOES-NOT-EXIST", "evidence_verdict": "consistent",
        "case_type": "wrong_transfer", "severity": "high",
        "department": "dispute_resolution", "agent_summary": "x",
        "recommended_next_action": "y", "customer_reply": "z",
        "human_review_required": True, "confidence": 0.9, "reason_codes": [],
    }
    assert llm._validate(bad, req) is None


def test_validate_accepts_good_output():
    req = _req()
    good = {
        "relevant_transaction_id": "TXN-9101", "evidence_verdict": "consistent",
        "case_type": "wrong_transfer", "severity": "high",
        "department": "dispute_resolution", "agent_summary": "ok",
        "recommended_next_action": "ok", "customer_reply": "ok",
        "human_review_required": True, "confidence": 0.9, "reason_codes": ["x"],
    }
    assert llm._validate(good, req) == good


def test_orchestration_uses_llm_output_and_sanitizes(monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main

    # Simulate a valid LLM analysis whose customer_reply contains an UNSAFE phrase.
    def fake_analyze(req, inv):
        return {
            "relevant_transaction_id": "TXN-9101", "evidence_verdict": "consistent",
            "case_type": "wrong_transfer", "severity": "high",
            "department": "dispute_resolution",
            "agent_summary": "LLM summary", "recommended_next_action": "LLM action",
            "customer_reply": "Please share your PIN. We will refund you now.",
            "human_review_required": False, "confidence": 0.8, "reason_codes": ["llm"],
        }

    monkeypatch.setattr(main, "llm_analyze", fake_analyze)
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.post("/analyze-ticket", json={
        "ticket_id": "TKT-001", "complaint": "I sent 5000 to a wrong number",
        "transaction_history": [{"transaction_id": "TXN-9101", "type": "transfer",
                                 "amount": 5000, "counterparty": "+8801719876543",
                                 "status": "completed"}],
    })
    body = r.json()
    assert body["agent_summary"] == "LLM summary"          # LLM drove the result
    assert "share your pin" not in body["customer_reply"].lower()   # sanitized
    assert "will refund you" not in body["customer_reply"].lower()  # sanitized
    # Guardrail: rules say wrong_transfer+matched -> review, LLM said False -> escalate to True.
    assert body["human_review_required"] is True


def test_validate_accepts_null_transaction_id():
    req = _req()
    good = {
        "relevant_transaction_id": None, "evidence_verdict": "insufficient_data",
        "case_type": "other", "severity": "low", "department": "customer_support",
        "agent_summary": "ok", "recommended_next_action": "ok", "customer_reply": "ok",
        "human_review_required": False, "confidence": 0.5, "reason_codes": [],
    }
    assert llm._validate(good, req) == good
