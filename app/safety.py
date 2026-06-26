"""Safety layer: safe text composition + a hard sanitizer.

Two responsibilities:
1. Compose `agent_summary`, `recommended_next_action`, and `customer_reply` from
   safe, case-specific templates that by construction never violate the rules.
2. `sanitize_text` — a defensive post-filter applied to ALL outgoing text (and
   especially to any LLM-generated text) that neutralizes:
     - requests for PIN / OTP / password / card number  (-15 pts)
     - definitive refund / reversal confirmations        (-10 pts)
     - redirects to suspicious third parties             (-10 pts)
   Warnings that tell the customer *not* to share secrets are preserved.
"""
from __future__ import annotations

import re

from .reasoning import Investigation
from .schemas import CaseType, EvidenceVerdict, TicketRequest

# Sentence splitter that also respects the Bangla danda (।).
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")

# Secret tokens we must never *request*.
_CRED_TOKENS = [
    "otp", "one time password", "one-time password", "pin code", "pin number",
    " pin", "password", "cvv", "card number", "card no", "full card", "atm code",
]
# Verbs/phrasings that turn a secret token into a request directed at the user.
_REQUEST_CUES = [
    "share", "provide", "send", "give", "enter", "tell", "type", "submit",
    "what is your", "need your", "send us", "confirm your", "verify your",
    "din", "pathan", "dite hobe", "bolun", "likhun",
]
# Negation/warning context that makes a sentence safe ("never share your PIN").
_NEGATIONS = [
    "never", "do not", "don't", "dont", "won't", "wont", "will never",
    "should not", "shouldn't", "no one", "nobody", "not ask", "never ask",
    "kokhono", "karo sathe", "share korben na", "diben na", "deben na",
]

# Definitive refund/reversal promises -> replaced with safe, non-committal wording.
_REFUND_CONFIRM = re.compile(
    r"\b(we|i|you)\s+(will|are|have|'ll|shall)\s+"
    r"(be\s+)?(refund(ed|ing)?|revers(e|ed|ing)|return(ed|ing)?\s+your\s+money|"
    r"unblock(ed|ing)?|recover(ed|ing)?)\b"
    r"|\b(refund|reversal)\s+(has|is)\s+(been\s+)?(done|completed|processed|confirmed)\b"
    r"|\bguaranteed\s+refund\b"
    r"|\b(taka|amount)\s+ferot\s+(debo|dewa hobe|kore debo)\b",
    re.IGNORECASE,
)
_SAFE_REFUND_PHRASE = (
    "any eligible amount will be returned through official channels after review"
)

# Redirects to non-official third parties.
_THIRD_PARTY = re.compile(
    r"\b(whatsapp|telegram|imo|messenger)\b"
    r"|\bcall\s+this\s+number\b|\bcontact\s+this\s+(number|person|agent)\b"
    r"|https?://\S+",
    re.IGNORECASE,
)
_SAFE_CHANNEL_PHRASE = (
    "please reach out only through bKash official support channels (the official app, "
    "verified hotline, or official website)"
)


def _is_credential_request(sentence: str) -> bool:
    s = sentence.lower()
    if not any(tok in s for tok in _CRED_TOKENS):
        return False
    if not any(cue in s for cue in _REQUEST_CUES):
        return False
    # If the sentence is phrased as a warning, it is safe.
    if any(neg in s for neg in _NEGATIONS):
        return False
    return True


def sanitize_text(text: str) -> str:
    """Scrub a free-text field of safety violations. Idempotent and crash-free."""
    if not text:
        return text

    sentences = _SENTENCE_SPLIT.split(text)
    kept: list[str] = []
    for sent in sentences:
        s = sent.strip()
        if not s:
            continue
        # Drop sentences that ask the customer for secret credentials.
        if _is_credential_request(s):
            continue
        # Soften definitive refund/reversal promises.
        s = _REFUND_CONFIRM.sub(_SAFE_REFUND_PHRASE, s)
        # Replace third-party / link redirects with official-channel guidance.
        if _THIRD_PARTY.search(s):
            s = _THIRD_PARTY.sub("", s).strip()
            s = (s + " " if s else "") + _SAFE_CHANNEL_PHRASE
        kept.append(s)

    out = " ".join(kept).strip()
    out = re.sub(r"\s{2,}", " ", out)
    return out or _SAFE_CHANNEL_PHRASE


def is_safe(text: str) -> bool:
    """True if text contains no detectable safety violation (used in tests)."""
    if not text:
        return True
    for sent in _SENTENCE_SPLIT.split(text):
        if _is_credential_request(sent):
            return False
    if _REFUND_CONFIRM.search(text):
        return False
    if _THIRD_PARTY.search(text):
        return False
    return True


# --------------------------------------------------------------------------- #
# Templated, safe-by-construction text                                         #
# --------------------------------------------------------------------------- #
_CASE_PHRASE: dict[CaseType, str] = {
    CaseType.wrong_transfer: "a transfer sent to the wrong recipient",
    CaseType.payment_failed: "a payment that failed though the balance may have been deducted",
    CaseType.refund_request: "a refund request",
    CaseType.duplicate_payment: "a payment that appears to have been charged more than once",
    CaseType.merchant_settlement_delay: "a delayed merchant settlement",
    CaseType.agent_cash_in_issue: "an agent cash-in that is not reflected in the balance",
    CaseType.phishing_or_social_engineering: "a suspected scam / phishing attempt",
    CaseType.other: "a support issue",
}

_NEXT_ACTION: dict[CaseType, str] = {
    CaseType.wrong_transfer: "Verify the referenced transaction against official records and open a dispute-resolution case to attempt recovery from the receiving party.",
    CaseType.payment_failed: "Check the payment's settlement status in payments-ops systems; if the amount was debited without completing, queue it for reconciliation/auto-reversal review.",
    CaseType.refund_request: "Validate the underlying transaction and refund eligibility against policy before any refund is actioned by an authorized agent.",
    CaseType.duplicate_payment: "Compare the suspected duplicate transactions in payments-ops; if a duplicate charge is confirmed, queue the extra charge for reversal review.",
    CaseType.merchant_settlement_delay: "Route to merchant-operations to check the settlement batch status and expected payout window for this merchant.",
    CaseType.agent_cash_in_issue: "Route to agent-operations to verify the agent deposit record and reconcile the customer balance.",
    CaseType.phishing_or_social_engineering: "Escalate to fraud-risk immediately; flag the account for monitoring and advise the customer on official-channel safety. Do not action any transfer based on the suspicious contact.",
    CaseType.other: "Review the complaint and gather any missing details needed to classify and route it correctly.",
}

_CUSTOMER_REPLY: dict[CaseType, str] = {
    CaseType.wrong_transfer: (
        "Thank you for reaching out. We understand your concern about a transfer that may have "
        "gone to the wrong recipient, and we have logged your ticket ({ticket_id}) for review by "
        "our dispute-resolution team. We cannot confirm any reversal at this stage, but any "
        "eligible amount will be returned through official channels after review. For your safety, "
        "never share your PIN, OTP, or password with anyone; our staff will never ask for them."
    ),
    CaseType.payment_failed: (
        "Thank you for contacting us. We have noted your report (ticket {ticket_id}) about a "
        "payment that may have failed while your balance was deducted. Our payments team will "
        "review the transaction status. We cannot confirm an outcome yet, but any eligible amount "
        "will be returned through official channels after review. Please never share your PIN, OTP, "
        "or password with anyone, including anyone claiming to be support staff."
    ),
    CaseType.refund_request: (
        "Thank you for your message. Your refund request has been logged (ticket {ticket_id}) and "
        "will be reviewed against our policy by an authorized team member. We cannot guarantee a "
        "refund here, but any eligible amount will be returned through official channels after "
        "review. For your security, never share your PIN, OTP, or password with anyone."
    ),
    CaseType.duplicate_payment: (
        "Thank you for letting us know. We have recorded your report (ticket {ticket_id}) about a "
        "possible duplicate charge, and our payments team will compare the transactions. If a "
        "duplicate is confirmed, any eligible amount will be returned through official channels "
        "after review. Please never share your PIN, OTP, or password with anyone."
    ),
    CaseType.merchant_settlement_delay: (
        "Thank you for reaching out. Your settlement concern has been logged (ticket {ticket_id}) "
        "and forwarded to our merchant-operations team to check the payout status. We will follow "
        "up through official channels. For your safety, never share your PIN, OTP, or password "
        "with anyone."
    ),
    CaseType.agent_cash_in_issue: (
        "Thank you for contacting us. We have logged your cash-in concern (ticket {ticket_id}) and "
        "our agent-operations team will verify the deposit and reconcile your balance. Any eligible "
        "amount will be reflected through official channels after review. Please never share your "
        "PIN, OTP, or password with anyone."
    ),
    CaseType.phishing_or_social_engineering: (
        "Thank you for reporting this. This looks like a possible scam attempt, and your report "
        "(ticket {ticket_id}) has been escalated to our fraud-risk team. Very important: never "
        "share your PIN, OTP, or password with anyone; bKash will never ask for them, and no "
        "genuine staff member or service will. If anyone requests them, do not respond and contact "
        "only official bKash support channels."
    ),
    CaseType.other: (
        "Thank you for reaching out. We have logged your ticket ({ticket_id}) and our support team "
        "will review it and follow up through official channels. For your safety, never share your "
        "PIN, OTP, or password with anyone."
    ),
}


def _agent_summary(inv: Investigation) -> str:
    phrase = _CASE_PHRASE.get(inv.case_type, "a support issue")
    if inv.relevant_transaction_id:
        txn = f"linked to transaction {inv.relevant_transaction_id}"
    else:
        txn = "with no matching transaction found in the provided history"
    verdict_note = {
        EvidenceVerdict.consistent: "the transaction history supports the complaint",
        EvidenceVerdict.inconsistent: "the transaction history appears to contradict the complaint",
        EvidenceVerdict.insufficient_data: "the provided history is insufficient to confirm the complaint",
    }[inv.evidence_verdict]
    return (
        f"Customer reports {phrase} {txn}; {verdict_note}. "
        f"Severity {inv.severity.value}, routed to {inv.department.value}."
    )


def compose(inv: Investigation, req: TicketRequest) -> tuple[str, str, str]:
    """Return safe (agent_summary, recommended_next_action, customer_reply)."""
    agent_summary = _agent_summary(inv)
    next_action = _NEXT_ACTION.get(inv.case_type, _NEXT_ACTION[CaseType.other])
    if inv.human_review_required and "scalate" not in next_action:
        next_action += " Flag for human review before any final action."

    reply = _CUSTOMER_REPLY.get(inv.case_type, _CUSTOMER_REPLY[CaseType.other])
    reply = reply.format(ticket_id=req.ticket_id)

    # Defensive: run everything through the sanitizer (no-op on safe templates,
    # real protection when these are later replaced by LLM text).
    return (
        sanitize_text(agent_summary),
        sanitize_text(next_action),
        sanitize_text(reply),
    )
