"""Deterministic investigation engine.

Given a ticket, decide:
  - relevant_transaction_id   (which transaction the complaint refers to, or None)
  - evidence_verdict          (consistent / inconsistent / insufficient_data)
  - case_type, severity, department
  - human_review_required, reason_codes, confidence

This is the evidence-reasoning core (35% of the score) and is fully deterministic:
fast, free, and reproducible. Text fields are composed separately in safety.py.
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

# Money thresholds (BDT) used for severity and high-value escalation.
HIGH_VALUE = 10_000
CRITICAL_VALUE = 50_000

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


@dataclass
class Investigation:
    """All deterministic decision outputs plus the signals behind them."""

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

    Handles `5000`, `5,000`, `5000 taka`, `5k`. Only amounts near a currency hint
    OR standalone numbers >= 50 are kept (to avoid grabbing PINs/years/counts).
    """
    t = normalize(text)
    amounts: list[float] = []

    # `5k` / `5 k` style.
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*k\b", t):
        amounts.append(float(m.group(1)) * 1000)

    # Plain numbers with optional thousands separators.
    for m in re.finditer(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", t):
        raw = m.group(0).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        # Keep if it looks like money: near a currency word, or a "round-ish" amount.
        window = t[max(0, m.start() - 12): m.end() + 8]
        near_currency = any(h in window for h in AMOUNT_HINTS)
        if near_currency or val >= 50:
            amounts.append(val)

    # De-dup while preserving order.
    seen: set[float] = set()
    out: list[float] = []
    for a in amounts:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def extract_phone_digits(text: str) -> list[str]:
    """Extract Bangladeshi-style phone numbers, normalized to trailing digits."""
    t = text or ""
    raw = re.findall(r"\+?8801\d{8}|\b01\d{9}\b", t)
    return [r[-10:] for r in raw]  # last 10 digits as a comparable key


def _amounts_match(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    # Exact, or within 1 BDT to tolerate float noise.
    return abs(a - b) <= 1.0


# --------------------------------------------------------------------------- #
# Transaction matching                                                         #
# --------------------------------------------------------------------------- #
def match_transaction(
    req: TicketRequest, amounts: list[float], case_type_hint: Optional[CaseType]
) -> tuple[Optional[TransactionEntry], float]:
    """Score each history entry against the complaint; return (best, score).

    Returns (None, 0.0) when history is empty or nothing clears the threshold.
    """
    history = req.transaction_history or []
    if not history:
        return None, 0.0

    complaint = normalize(req.complaint)
    phones = set(extract_phone_digits(req.complaint))

    best: Optional[TransactionEntry] = None
    best_score = 0.0

    for entry in history:
        score = 0.0

        # Amount match — strongest signal.
        if entry.amount is not None and any(_amounts_match(entry.amount, a) for a in amounts):
            score += 3.0

        # Counterparty / phone match.
        if entry.counterparty:
            cp_digits = (entry.counterparty or "")[-10:]
            if cp_digits and cp_digits in phones:
                score += 3.0
            elif normalize(entry.counterparty) and normalize(entry.counterparty) in complaint:
                score += 1.5

        # Transaction type aligns with the inferred case type.
        if case_type_hint and entry.type in CASE_TXN_TYPE.get(case_type_hint, set()):
            score += 1.0

        # Status word in complaint matches this entry's status.
        if entry.status:
            for canon, words in STATUS_WORDS.items():
                if entry.status == canon and any(w in complaint for w in words):
                    score += 1.0
                    break

        # Explicit transaction id mentioned in the complaint.
        if entry.transaction_id and normalize(entry.transaction_id) in complaint:
            score += 4.0

        # Tiny recency nudge so ties prefer the latest transaction.
        if entry.timestamp:
            score += 0.001 * _timestamp_rank(entry.timestamp)

        if score > best_score:
            best_score = score
            best = entry

    # Require a minimum signal to claim a match.
    if best_score >= 1.0:
        return best, best_score
    return None, 0.0


def _timestamp_rank(ts: str) -> float:
    """Cheap monotonic rank from an ISO-ish timestamp (digits only)."""
    digits = re.sub(r"\D", "", ts or "")
    try:
        return float(digits[:14]) if digits else 0.0
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- #
# Classification                                                               #
# --------------------------------------------------------------------------- #
def classify_case_type(req: TicketRequest) -> tuple[CaseType, int]:
    """Keyword + evidence classification. Returns (case_type, hit_strength)."""
    complaint = normalize(req.complaint)

    scores: dict[str, int] = {}
    for case, words in CASE_KEYWORDS.items():
        hits = sum(1 for w in words if w in complaint)
        if hits:
            scores[case] = hits

    # Evidence-based nudges from the transaction history types present.
    history_types = {e.type for e in (req.transaction_history or []) if e.type}
    if "settlement" in history_types:
        scores["merchant_settlement_delay"] = scores.get("merchant_settlement_delay", 0) + 1
    if "cash_in" in history_types:
        scores["agent_cash_in_issue"] = scores.get("agent_cash_in_issue", 0) + 1

    # Duplicate detection: two completed entries sharing amount + counterparty.
    if _has_duplicate(req):
        scores["duplicate_payment"] = scores.get("duplicate_payment", 0) + 2

    if not scores:
        return CaseType.other, 0

    # Safety-critical: phishing wins ties so risky cases are never under-routed.
    best = max(scores.items(), key=lambda kv: (kv[1], kv[0] == "phishing_or_social_engineering"))
    return CaseType(best[0]), best[1]


def _has_duplicate(req: TicketRequest) -> bool:
    seen: set[tuple] = set()
    for e in req.transaction_history or []:
        if e.amount is None:
            continue
        key = (e.amount, e.counterparty, e.type)
        if key in seen:
            return True
        seen.add(key)
    return False


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

    if not history:
        return EvidenceVerdict.insufficient_data
    if matched is None:
        # History exists but nothing matches the complaint -> can't determine.
        return EvidenceVerdict.insufficient_data

    status = matched.status

    # Amount mismatch is a strong contradiction signal.
    if amounts and matched.amount is not None and not any(
        _amounts_match(matched.amount, a) for a in amounts
    ):
        return EvidenceVerdict.inconsistent

    if case_type == CaseType.payment_failed:
        if status in {"failed", "reversed"}:
            return EvidenceVerdict.consistent
        if status == "completed":
            return EvidenceVerdict.inconsistent
        return EvidenceVerdict.insufficient_data  # pending / unknown

    if case_type == CaseType.wrong_transfer:
        if status == "completed":
            return EvidenceVerdict.consistent  # money did leave the account
        if status in {"failed", "reversed"}:
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
        # A matching transaction gives the refund request a basis.
        return EvidenceVerdict.consistent

    # phishing / other: a matched transaction is weak signal either way.
    return EvidenceVerdict.insufficient_data


def determine_severity(
    case_type: CaseType, amounts: list[float], matched: Optional[TransactionEntry]
) -> Severity:
    amount = _peak_amount(amounts, matched)

    if case_type == CaseType.phishing_or_social_engineering:
        return Severity.critical if (amount and amount >= HIGH_VALUE) else Severity.high

    # Loss-type cases (money already moved to the wrong place / charged twice)
    # carry a higher base than service-delay or refund-request cases.
    if case_type in {CaseType.wrong_transfer, CaseType.duplicate_payment}:
        base = Severity.high
    elif case_type == CaseType.other:
        base = Severity.low
    else:
        base = Severity.medium

    if amount is not None:
        if amount >= CRITICAL_VALUE:
            return Severity.critical
        if amount >= HIGH_VALUE and base != Severity.low:
            return Severity.high
    return base


def _peak_amount(amounts: list[float], matched: Optional[TransactionEntry]) -> Optional[float]:
    vals = list(amounts)
    if matched and matched.amount is not None:
        vals.append(matched.amount)
    return max(vals) if vals else None


def route_department(
    case_type: CaseType, verdict: EvidenceVerdict, severity: Severity
) -> Department:
    dept = DEPARTMENT_MAP[case_type]
    # Contested / non-trivial refunds escalate to dispute resolution.
    if case_type == CaseType.refund_request and (
        verdict != EvidenceVerdict.consistent or severity in {Severity.high, Severity.critical}
    ):
        return Department.dispute_resolution
    return dept


def needs_human_review(
    case_type: CaseType,
    verdict: EvidenceVerdict,
    severity: Severity,
    amounts: list[float],
    matched: Optional[TransactionEntry],
) -> bool:
    if case_type in {
        CaseType.wrong_transfer,
        CaseType.duplicate_payment,
        CaseType.phishing_or_social_engineering,
    }:
        return True
    if severity in {Severity.high, Severity.critical}:
        return True
    if verdict != EvidenceVerdict.consistent:
        return True
    amount = _peak_amount(amounts, matched)
    if amount is not None and amount >= HIGH_VALUE:
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
    severity = determine_severity(case_type, amounts, matched)
    department = route_department(case_type, verdict, severity)
    human_review = needs_human_review(case_type, verdict, severity, amounts, matched)
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
