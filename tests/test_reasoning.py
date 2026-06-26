"""Unit tests for the deterministic investigation engine."""
from app.reasoning import extract_amounts, investigate
from app.schemas import (
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
    TicketRequest,
    TransactionEntry,
)


def _req(complaint: str, history=None, **kw) -> TicketRequest:
    return TicketRequest(
        ticket_id=kw.pop("ticket_id", "TKT-T"),
        complaint=complaint,
        transaction_history=history or [],
        **kw,
    )


def test_extract_amounts_handles_separators_and_k():
    assert 5000 in extract_amounts("I sent 5000 taka")
    assert 5000 in extract_amounts("sent 5,000 BDT")
    assert 5000 in extract_amounts("paid 5k to merchant")


def test_wrong_transfer_consistent_with_completed_transfer():
    history = [
        TransactionEntry(
            transaction_id="TXN-1", timestamp="2026-04-14T14:08:22Z",
            type="transfer", amount=5000, counterparty="+8801719876543",
            status="completed",
        )
    ]
    inv = investigate(_req("I sent 5000 taka to a wrong number by mistake", history))
    assert inv.case_type == CaseType.wrong_transfer
    assert inv.relevant_transaction_id == "TXN-1"
    assert inv.evidence_verdict == EvidenceVerdict.consistent
    assert inv.department == Department.dispute_resolution
    assert inv.human_review_required is True


def test_payment_failed_inconsistent_when_actually_completed():
    history = [
        TransactionEntry(transaction_id="TXN-2", type="payment", amount=300,
                         status="completed")
    ]
    inv = investigate(_req("My payment failed but 300 taka was deducted", history))
    assert inv.case_type == CaseType.payment_failed
    assert inv.evidence_verdict == EvidenceVerdict.inconsistent
    assert inv.department == Department.payments_ops


def test_payment_failed_consistent_when_failed():
    history = [
        TransactionEntry(transaction_id="TXN-3", type="payment", amount=300,
                         status="failed")
    ]
    inv = investigate(_req("payment failed kintu 300 taka kete niyeche", history))
    assert inv.evidence_verdict == EvidenceVerdict.consistent


def test_phishing_takes_priority_and_routes_to_fraud():
    inv = investigate(_req("Someone called asking for my OTP and PIN to claim a prize"))
    assert inv.case_type == CaseType.phishing_or_social_engineering
    assert inv.department == Department.fraud_risk
    assert inv.severity in {Severity.high, Severity.critical}
    assert inv.human_review_required is True


def test_empty_history_is_insufficient_data():
    inv = investigate(_req("I want a refund of 200 taka"))
    assert inv.evidence_verdict == EvidenceVerdict.insufficient_data


def test_no_match_in_history_is_insufficient_data():
    history = [TransactionEntry(transaction_id="TXN-9", type="cash_in", amount=99,
                                status="completed")]
    inv = investigate(_req("I sent 7777 taka to a wrong number", history))
    assert inv.relevant_transaction_id is None
    assert inv.evidence_verdict == EvidenceVerdict.insufficient_data


def test_duplicate_payment_detected():
    history = [
        TransactionEntry(transaction_id="TXN-A", type="payment", amount=500,
                         counterparty="MERCH-1", status="completed"),
        TransactionEntry(transaction_id="TXN-B", type="payment", amount=500,
                         counterparty="MERCH-1", status="completed"),
    ]
    inv = investigate(_req("I was charged twice 500 taka for the same payment", history))
    assert inv.case_type == CaseType.duplicate_payment
    assert inv.evidence_verdict == EvidenceVerdict.consistent
    assert inv.department == Department.payments_ops


def test_high_value_escalates_severity_and_review():
    history = [TransactionEntry(transaction_id="TXN-H", type="transfer",
                                amount=60000, status="completed")]
    inv = investigate(_req("Sent 60000 taka to the wrong person", history))
    assert inv.severity == Severity.critical
    assert inv.human_review_required is True


def test_all_required_enum_fields_present():
    inv = investigate(_req("random complaint text"))
    assert isinstance(inv.case_type, CaseType)
    assert isinstance(inv.severity, Severity)
    assert isinstance(inv.department, Department)
    assert isinstance(inv.evidence_verdict, EvidenceVerdict)
