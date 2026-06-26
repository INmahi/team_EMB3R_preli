"""Deterministic investigation engine.

Given a ticket, decide:
  - relevant_transaction_id   (which transaction the complaint refers to, or None)
  - evidence_verdict          (consistent / inconsistent / insufficient_data)
  - case_type, severity, department
  - human_review_required, reason_codes, confidence

This is the evidence-reasoning core (35% of the score) and is fully deterministic:
fast, free, and reproducible. Text fields are composed separately in safety.py.
Rules are calibrated against the public sample case pack (see tests/test_samples.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .keywords import AMOUNT_HINTS, CASE_KEYWORDS, STATUS_WORDS
from .schemas import (
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
    TicketRequest,
    TransactionEntry,
)

# Money thresholds (BDT).
HIGH_VALUE = 10_000
CRITICAL_VALUE = 50_000
# Numbers above this are treated as non-money (IDs/phones that slipped through).
AMOUNT_SANITY_MAX = 10_000_000

# Deterministic case_type -> department map (Problem Statement Section 7.2).
DEPARTMENT_MAP: dict[CaseType, Department] = {
    CaseType.wrong_transfer: Department.dispute_resolution,
    CaseType.payment_failed: Department.payments_ops,
    CaseType.refund_request: Department.customer_support,  # overridden if contested
    CaseType.duplicate_payment: Department.payments_ops,
    CaseType.merchant_settlement_delay: Department.merchant_operations,
    CaseType.agent_cash_in_issue: Department.agent_operations,
    CaseType.phishing_or_social_engineering: Department.fraud_risk,
    CaseType.other: Department.customer_support,
}

# case_type -> transaction type that most naturally supports it.
CASE_TXN_TYPE: dict[CaseType, set[str]] = {
    CaseType.wrong_transfer: {"transfer"},
    CaseType.payment_failed: {"payment", "transfer"},
    CaseType.refund_request: {"payment", "transfer", "refund"},
    CaseType.duplicate_payment: {"payment", "transfer"},
    CaseType.merchant_settlement_delay: {"settlement"},
    CaseType.agent_cash_in_issue: {"cash_in"},
}

# Cases that, once a transaction is identified, need a human to authorize recovery/dispute.
REVIEW_IF_MATCHED = {
    CaseType.wrong_transfer,
    CaseType.duplicate_payment,
    CaseType.agent_cash_in_issue,
}

# Loss-type cases that are "high" severity once the evidence confirms them.
LOSS_TYPES = {
    CaseType.wrong_transfer,
    CaseType.payment_failed,
    CaseType.agent_cash_in_issue,
    CaseType.duplicate_payment,
}

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_PHONE_RE = re.compile(r"\+?8801\d{8}|\b01\d{9}\b")


@dataclass
class Investigation:
    ticket_id: str
    relevant_transaction_id: Optional[str]
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    human_review_required: bool
    confidence: float
    reason_codes: list[str] = field(default_factory=list)
    matched: Optional[TransactionEntry] = None
    amount_in_complaint: Optional[float] = None


# --------------------------------------------------------------------------- #
# Text helpers                                                                 #
# --------------------------------------------------------------------------- #
def normalize(text: str) -> str:
    return (text or "").lower().strip()


def extract_amounts(text: str) -> list[float]:
    """Pull plausible money amounts from complaint text.

    Bangla numerals are converted to ASCII. Phone numbers are removed first so
    they are never mistaken for amounts. Numbers are kept if near a currency hint
    or >= 50, and absurdly large values (IDs) are dropped.
    """
    t = normalize(text).translate(_BN_DIGITS)
    t = _PHONE_RE.sub(" ", t)  # drop phone numbers before parsing amounts

    amounts: list[float] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*k\b", t):
        amounts.append(float(m.group(1)) * 1000)

    for m in re.finditer(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", t):
        raw = m.group(0).replace(",", "")
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 11:  # phone-length leftover -> not money
            continue
        try:
            val = float(raw)
        except ValueError:
            continue
        if val > AMOUNT_SANITY_MAX:
            continue
        window = t[max(0, m.start() - 12): m.end() + 8]
        if any(h in window for h in AMOUNT_HINTS) or val >= 50:
            amounts.append(val)

    seen: set[float] = set()
    out: list[float] = []
    for a in amounts:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def extract_phone_digits(text: str) -> list[str]:
    raw = _PHONE_RE.findall(text or "")
    return [r[-10:] for r in raw]


def _amounts_match(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= 1.0


def _timestamp_rank(ts: str) -> float:
    digits = re.sub(r"\D", "", ts or "")
    try:
        return float(digits[:14]) if digits else 0.0
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- #
# Transaction matching                                                         #
# --------------------------------------------------------------------------- #
def _score_entry(
    entry: TransactionEntry, complaint: str, amounts: list[float],
    phones: set[str], case_type_hint: Optional[CaseType],
) -> float:
    """Core match score for one entry (excludes the recency tiebreak)."""
    score = 0.0
    if entry.amount is not None and any(_amounts_match(entry.amount, a) for a in amounts):
        score += 3.0
    if entry.counterparty:
        cp_digits = (entry.counterparty or "")[-10:]
        if cp_digits and cp_digits in phones:
            score += 3.0
        elif normalize(entry.counterparty) and normalize(entry.counterparty) in complaint:
            score += 1.5
    if case_type_hint and entry.type in CASE_TXN_TYPE.get(case_type_hint, set()):
        score += 1.0
    if entry.status:
        for canon, words in STATUS_WORDS.items():
            if entry.status == canon and any(w in complaint for w in words):
                score += 1.0
                break
    if entry.transaction_id and normalize(entry.transaction_id) in complaint:
        score += 4.0
    return score


def match_transaction(
    req: TicketRequest, amounts: list[float], case_type_hint: Optional[CaseType]
) -> tuple[Optional[TransactionEntry], float]:
    """Return (best_entry, score). Returns (None, 0.0) when no clear single match.

    If several entries tie for the top score (ambiguous), we refuse to guess and
    return None -- EXCEPT for duplicate_payment, where the latest tied entry (the
    likely duplicate) is returned.
    """
    history = req.transaction_history or []
    if not history:
        return None, 0.0

    complaint = normalize(req.complaint).translate(_BN_DIGITS)
    phones = set(extract_phone_digits(req.complaint))

    scored = [
        (_score_entry(e, complaint, amounts, phones, case_type_hint), e) for e in history
    ]
    max_core = max(s for s, _ in scored)
    if max_core < 1.0:
        return None, 0.0

    top = [e for s, e in scored if s >= max_core - 0.01]
    if len(top) > 1 and len({e.transaction_id for e in top}) > 1:
        if case_type_hint == CaseType.duplicate_payment:
            best = max(top, key=lambda e: _timestamp_rank(e.timestamp))
            return best, max_core
        return None, 0.0  # genuinely ambiguous -> do not guess

    best = max(scored, key=lambda t: (t[0], _timestamp_rank(t[1].timestamp)))[1]
    return best, max_core


# --------------------------------------------------------------------------- #
# Classification                                                               #
# --------------------------------------------------------------------------- #
def classify_case_type(req: TicketRequest) -> tuple[CaseType, int]:
    """Keyword + evidence classification. Returns (case_type, hit_strength).

    With zero textual cues we return `other` and ignore data-only nudges -- the
    service should not invent a classification from transaction data alone.
    """
    complaint = normalize(req.complaint)

    scores: dict[str, int] = {}
    for case, words in CASE_KEYWORDS.items():
        hits = sum(1 for w in words if w in complaint)
        if hits:
            scores[case] = hits

    if not scores:
        return CaseType.other, 0

    history_types = {e.type for e in (req.transaction_history or []) if e.type}
    if "settlement" in history_types and "merchant_settlement_delay" in scores:
        scores["merchant_settlement_delay"] += 1
    if "cash_in" in history_types and "agent_cash_in_issue" in scores:
        scores["agent_cash_in_issue"] += 1
    if _has_duplicate(req):
        scores["duplicate_payment"] = scores.get("duplicate_payment", 0) + 2

    best = max(scores.items(), key=lambda kv: (kv[1], kv[0] == "phishing_or_social_engineering"))
    return CaseType(best[0]), best[1]


def _has_duplicate(req: TicketRequest) -> bool:
    # A genuine duplicate charge is two COMPLETED payments with the same
    # amount/counterparty/type. A completed + failed pair is not a duplicate.
    seen: set[tuple] = set()
    for e in req.transaction_history or []:
        if e.amount is None or e.status != "completed":
            continue
        key = (e.amount, e.counterparty, e.type)
        if key in seen:
            return True
        seen.add(key)
    return False


def _established_recipient(req: TicketRequest, matched: Optional[TransactionEntry]) -> bool:
    """True if the matched counterparty has >=2 OTHER completed transfers/payments.

    A history of repeated transfers to the same recipient contradicts a
    'wrong transfer' claim (the recipient is clearly established).
    """
    if not matched or not matched.counterparty:
        return False
    cp = matched.counterparty
    others = [
        e for e in (req.transaction_history or [])
        if e is not matched and e.counterparty == cp
        and e.status == "completed" and e.type in {"transfer", "payment"}
    ]
    return len(others) >= 2


# --------------------------------------------------------------------------- #
# Verdict, severity, routing                                                   #
# --------------------------------------------------------------------------- #
def determine_verdict(
    case_type: CaseType,
    matched: Optional[TransactionEntry],
    amounts: list[float],
    req: TicketRequest,
) -> EvidenceVerdict:
    history = req.transaction_history or []
    if not history or matched is None:
        return EvidenceVerdict.insufficient_data

    status = matched.status

    if amounts and matched.amount is not None and not any(
        _amounts_match(matched.amount, a) for a in amounts
    ):
        return EvidenceVerdict.inconsistent

    if case_type == CaseType.wrong_transfer:
        if _established_recipient(req, matched):
            return EvidenceVerdict.inconsistent  # repeat recipient contradicts claim
        if status == "completed":
            return EvidenceVerdict.consistent
        if status in {"failed", "reversed"}:
            return EvidenceVerdict.inconsistent
        return EvidenceVerdict.insufficient_data

    if case_type == CaseType.payment_failed:
        if status in {"failed", "reversed"}:
            return EvidenceVerdict.consistent
        if status == "completed":
            return EvidenceVerdict.inconsistent
        return EvidenceVerdict.insufficient_data

    if case_type == CaseType.duplicate_payment:
        return EvidenceVerdict.consistent if _has_duplicate(req) else EvidenceVerdict.inconsistent

    if case_type == CaseType.merchant_settlement_delay:
        if status in {"pending", "failed"}:
            return EvidenceVerdict.consistent
        if status == "completed":
            return EvidenceVerdict.inconsistent
        return EvidenceVerdict.insufficient_data

    if case_type == CaseType.agent_cash_in_issue:
        if status in {"failed", "pending"}:
            return EvidenceVerdict.consistent
        if status == "completed":
            return EvidenceVerdict.inconsistent
        return EvidenceVerdict.insufficient_data

    if case_type == CaseType.refund_request:
        return EvidenceVerdict.consistent

    return EvidenceVerdict.insufficient_data


def determine_severity(
    case_type: CaseType,
    verdict: EvidenceVerdict,
    amounts: list[float],
    matched: Optional[TransactionEntry],
) -> Severity:
    if case_type == CaseType.phishing_or_social_engineering:
        return Severity.critical

    amount = _peak_amount(amounts, matched)
    loss_confirmed = case_type in LOSS_TYPES and verdict == EvidenceVerdict.consistent
    if loss_confirmed:
        if amount is not None and amount >= CRITICAL_VALUE:
            return Severity.critical
        return Severity.high

    if case_type == CaseType.refund_request:
        return Severity.low
    if case_type == CaseType.other:
        return Severity.low
    return Severity.medium


def _peak_amount(amounts: list[float], matched: Optional[TransactionEntry]) -> Optional[float]:
    vals = list(amounts)
    if matched and matched.amount is not None:
        vals.append(matched.amount)
    return max(vals) if vals else None


def route_department(
    case_type: CaseType, verdict: EvidenceVerdict, severity: Severity
) -> Department:
    if case_type == CaseType.refund_request and (
        verdict == EvidenceVerdict.inconsistent or severity in {Severity.high, Severity.critical}
    ):
        return Department.dispute_resolution
    return DEPARTMENT_MAP[case_type]


def needs_human_review(
    case_type: CaseType, verdict: EvidenceVerdict, matched: Optional[TransactionEntry]
) -> bool:
    if case_type == CaseType.phishing_or_social_engineering:
        return True
    if verdict == EvidenceVerdict.inconsistent:
        return True
    if case_type in REVIEW_IF_MATCHED and matched is not None:
        return True
    return False


def _confidence(
    case_strength: int, matched: Optional[TransactionEntry], verdict: EvidenceVerdict
) -> float:
    score = 0.45
    if case_strength >= 1:
        score += 0.2
    if case_strength >= 2:
        score += 0.1
    if matched is not None:
        score += 0.2
    if verdict == EvidenceVerdict.insufficient_data:
        score -= 0.15
    return round(max(0.1, min(0.97, score)), 2)


def _build_reason_codes(
    case_type: CaseType,
    verdict: EvidenceVerdict,
    matched: Optional[TransactionEntry],
    severity: Severity,
) -> list[str]:
    codes = [case_type.value]
    codes.append("transaction_match" if matched else "no_transaction_match")
    codes.append(f"evidence_{verdict.value}")
    if severity in {Severity.high, Severity.critical}:
        codes.append("high_value" if severity == Severity.critical else "elevated_severity")
    if case_type == CaseType.phishing_or_social_engineering:
        codes.append("fraud_signal")
    return codes


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #
def investigate(req: TicketRequest) -> Investigation:
    amounts = extract_amounts(req.complaint)

    case_type, strength = classify_case_type(req)
    matched, _score = match_transaction(req, amounts, case_type)
    verdict = determine_verdict(case_type, matched, amounts, req)
    severity = determine_severity(case_type, verdict, amounts, matched)
    department = route_department(case_type, verdict, severity)
    human_review = needs_human_review(case_type, verdict, matched)
    confidence = _confidence(strength, matched, verdict)
    reason_codes = _build_reason_codes(case_type, verdict, matched, severity)

    return Investigation(
        ticket_id=req.ticket_id,
        relevant_transaction_id=matched.transaction_id if matched else None,
        evidence_verdict=verdict,
        case_type=case_type,
        severity=severity,
        department=department,
        human_review_required=human_review,
        confidence=confidence,
        reason_codes=reason_codes,
        matched=matched,
        amount_in_complaint=amounts[0] if amounts else None,
    )
