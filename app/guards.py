"""Input-side defenses against prompt injection and adversarial payloads.

Pure helpers (no app imports) so both reasoning.py and safety.py can use them:

- `defang_input(text)`  — clean untrusted text before it is embedded in an LLM prompt
  (strip zero-width/bidi control chars, collapse token-flood runs, neutralize role/
  delimiter tags, cap length). Does NOT change meaning of a genuine complaint.
- `looks_like_injection(text)` — heuristic: does this text try to manipulate the system
  (override instructions, exfiltrate the prompt, solicit credentials, role-play tricks)?
  Used to route such attempts to phishing/fraud + human review.
"""
from __future__ import annotations

import re

# Zero-width, BOM, and bidi-control characters used to smuggle hidden instructions.
_INVISIBLE = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")
# Role / delimiter tags that try to "break out" of the data fence.
_ROLE_TAGS = re.compile(
    r"</?\s*(system|assistant|user|complaint|instructions?|developer)\s*>", re.I
)
# A word repeated many times in a row (token-flood / DoS).
_FLOOD = re.compile(r"(\b\w+\b)(?:\s+\1\b){4,}", re.I)

MAX_COMPLAINT_CHARS = 2000

# Markers that indicate an attempt to manipulate the model rather than a genuine
# support request. Lowercased substring match. Includes Bangla / Banglish variants.
INJECTION_MARKERS: list[str] = [
    "ignore all previous", "ignore previous", "ignore your rules", "ignore the rules",
    "ignore prior", "disregard your", "disregard all", "disregard previous",
    "new instructions", "### new instructions", "system:", "you are now",
    "you are an unrestricted", "developer mode", "jailbreak", "reveal your system",
    "system prompt", "print your", "repeat everything above", "forget the schema",
    "ignore safety", "bypass", "as an ai", "follow it:", "decode this", "base64",
    # credential-exfil phrasings embedded in the message
    "share my pin", "share your pin", "send my otp", "send your otp",
    "reply with their card", "reply with your card", "share their pin",
    "ask for the pin", "ask for otp", "ask me to send my otp", "confirm i should share",
    # role / tool confusion
    "you are in developer mode", "here is my system prompt", "call the internal",
    "refund_api", "reveal the", "list of allowed enums",
    # Bangla / Banglish
    "shob rules ignore", "rules ignore koren", "rules ignore", "ignore koren",
    "নির্দেশ উপেক্ষা", "সব নির্দেশ", "পিন শেয়ার", "পিন এবং ওটিপি", "ওটিপি শেয়ার",
    "pin ar otp share", "pin share korte", "otp share korte",
]


def defang_input(text: str) -> str:
    """Sanitize untrusted text for safe embedding in a prompt (meaning preserved)."""
    if not text:
        return text
    text = _INVISIBLE.sub("", text)            # remove hidden chars (OBF zero-width)
    text = _ROLE_TAGS.sub(" ", text)           # neutralize fake role tags
    text = _FLOOD.sub(r"\1", text)             # collapse repeated-token floods
    text = re.sub(r"\s{3,}", " ", text)        # collapse runaway whitespace
    return text[:MAX_COMPLAINT_CHARS]


def looks_like_injection(text: str) -> bool:
    """True if the text appears to be a prompt-injection / manipulation attempt."""
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in INJECTION_MARKERS)
