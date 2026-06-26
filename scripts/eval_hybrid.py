"""Evaluate the FULL hybrid pipeline (LLM + guardrails) via the app endpoint.

Reads LLM_* from env. Compares each sample case to expected_output on the fields
the judge treats as functional equivalence (transaction id, verdict, case_type,
department, severity) plus a customer_reply safety check.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.safety import is_safe  # noqa: E402

PACK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "samples", "SUST_Preli_Sample_Cases.json")
EQUIV = ["relevant_transaction_id", "evidence_verdict", "case_type", "department", "severity"]

with open(PACK, encoding="utf-8") as f:
    cases = json.load(f)["cases"]

client = TestClient(app)
print(f"LLM active: {settings.llm_active()}  model={settings.LLM_MODEL}\n")

ok = 0
for case in cases:
    out = client.post("/analyze-ticket", json=case["input"]).json()
    exp = case["expected_output"]
    diffs = {f: (out.get(f), exp[f]) for f in EQUIV if out.get(f) != exp[f]}
    safe = is_safe(out["customer_reply"])
    if not diffs and safe:
        ok += 1
        print(f"  PASS {case['id']}")
    else:
        print(f"  FAIL {case['id']}  diffs={diffs} safe={safe}")

print(f"\nHybrid pipeline: {ok}/{len(cases)} functionally equivalent + safe")
