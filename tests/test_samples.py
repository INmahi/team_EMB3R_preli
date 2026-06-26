"""Validate the service against the public sample case pack.

Checks functional equivalence on the fields the judge compares: relevant_transaction_id,
evidence_verdict, case_type, department, severity, human_review_required — plus a safety
check on customer_reply. Skips automatically if the sample pack is not present.
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.safety import is_safe

SAMPLES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "samples", "SUST_Preli_Sample_Cases.json",
)

client = TestClient(app)


def _load_cases():
    if not os.path.exists(SAMPLES_PATH):
        return []
    with open(SAMPLES_PATH, encoding="utf-8") as f:
        return json.load(f)["cases"]


CASES = _load_cases()
CHECK_FIELDS = [
    "relevant_transaction_id", "evidence_verdict", "case_type",
    "department", "severity", "human_review_required",
]


@pytest.mark.skipif(not CASES, reason="sample pack not present")
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_sample_case(case):
    r = client.post("/analyze-ticket", json=case["input"])
    assert r.status_code == 200, f"{case['id']}: HTTP {r.status_code}"
    out = r.json()
    exp = case["expected_output"]

    assert is_safe(out["customer_reply"]), f"{case['id']}: unsafe customer_reply"

    mismatches = {
        f: (out.get(f), exp[f]) for f in CHECK_FIELDS if f in exp and out.get(f) != exp[f]
    }
    assert not mismatches, f"{case['id']} mismatches (got, expected): {mismatches}"
