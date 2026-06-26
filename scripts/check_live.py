"""Run the 10 sample cases against a live base URL and report matches.

Usage: python scripts/check_live.py https://your-domain.up.railway.app
"""
import json
import os
import sys

import httpx

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
PACK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "samples", "SUST_Preli_Sample_Cases.json")
FIELDS = ["relevant_transaction_id", "evidence_verdict", "case_type",
          "department", "severity", "human_review_required"]

with open(PACK, encoding="utf-8") as f:
    cases = json.load(f)["cases"]

passed = 0
with httpx.Client(timeout=30) as c:
    for case in cases:
        r = c.post(f"{BASE}/analyze-ticket", json=case["input"])
        out = r.json()
        exp = case["expected_output"]
        bad = {f: (out.get(f), exp[f]) for f in FIELDS if out.get(f) != exp[f]}
        if not bad and r.status_code == 200:
            passed += 1
            print(f"  PASS {case['id']}")
        else:
            print(f"  FAIL {case['id']} ({r.status_code}) {bad}")

print(f"\n{passed}/{len(cases)} sample cases match against {BASE}")
