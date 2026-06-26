"""API-contract tests via FastAPI's TestClient."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

SAMPLE = {
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
    "language": "en",
    "channel": "in_app_chat",
    "user_type": "customer",
    "campaign_context": "boishakh_bonanza_day_1",
    "transaction_history": [
        {
            "transaction_id": "TXN-9101",
            "timestamp": "2026-04-14T14:08:22Z",
            "type": "transfer",
            "amount": 5000,
            "counterparty": "+8801719876543",
            "status": "completed",
        }
    ],
}

REQUIRED_FIELDS = {
    "ticket_id", "relevant_transaction_id", "evidence_verdict", "case_type",
    "severity", "department", "agent_summary", "recommended_next_action",
    "customer_reply", "human_review_required",
}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_analyze_ticket_happy_path():
    r = client.post("/analyze-ticket", json=SAMPLE)
    assert r.status_code == 200
    body = r.json()
    assert REQUIRED_FIELDS.issubset(body.keys())
    assert body["ticket_id"] == "TKT-001"
    assert body["relevant_transaction_id"] == "TXN-9101"
    assert body["evidence_verdict"] == "consistent"
    assert body["case_type"] == "wrong_transfer"
    assert body["department"] == "dispute_resolution"
    assert body["human_review_required"] is True


def test_missing_required_field_returns_400():
    r = client.post("/analyze-ticket", json={"complaint": "no ticket id here"})
    assert r.status_code == 400


def test_malformed_json_returns_400():
    r = client.post(
        "/analyze-ticket",
        content=b"{not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_empty_complaint_returns_422():
    r = client.post("/analyze-ticket", json={"ticket_id": "TKT-X", "complaint": "   "})
    assert r.status_code == 422


def test_empty_history_does_not_crash():
    r = client.post(
        "/analyze-ticket",
        json={"ticket_id": "TKT-Y", "complaint": "Someone asked for my OTP, scam call"},
    )
    assert r.status_code == 200
    assert r.json()["case_type"] == "phishing_or_social_engineering"


def test_extra_unknown_fields_are_tolerated():
    payload = dict(SAMPLE, ticket_id="TKT-Z", surprise_field={"x": 1})
    r = client.post("/analyze-ticket", json=payload)
    assert r.status_code == 200
