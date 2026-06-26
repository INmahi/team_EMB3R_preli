"""Compare deterministic vs LLM analysis against the sample pack.

Reads LLM_* from the environment (never hard-coded). For each sample case it runs:
  - the deterministic engine (investigate)
  - the LLM analysis (llm.analyze), if configured
and reports per-field agreement with expected_output, plus LLM latency.

Usage (PowerShell):
  $env:LLM_ENABLED="true"
  $env:LLM_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
  $env:LLM_MODEL="gemini-2.0-flash"
  $env:LLM_API_KEY="<key>"
  python scripts/eval_llm.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import llm
from app.config import settings
from app.reasoning import investigate
from app.schemas import TicketRequest

PACK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "samples", "SUST_Preli_Sample_Cases.json")
FIELDS = ["relevant_transaction_id", "evidence_verdict", "case_type",
          "department", "severity", "human_review_required"]

with open(PACK, encoding="utf-8") as f:
    cases = json.load(f)["cases"]

print(f"LLM active: {settings.llm_active()}  model={settings.LLM_MODEL}\n")

det_score = 0
llm_score = 0
llm_used = 0

for case in cases:
    req = TicketRequest(**case["input"])
    exp = case["expected_output"]

    inv = investigate(req)
    det = {f: getattr(inv, f) for f in FIELDS}
    det = {f: (v.value if hasattr(v, "value") else v) for f, v in det.items()}
    det_ok = all(det[f] == exp[f] for f in FIELDS)
    det_score += det_ok

    t0 = time.time()
    data = llm.analyze(req, inv)
    dt = time.time() - t0

    if data is None:
        print(f"{case['id']}: det={'OK' if det_ok else 'X '}  llm=FALLBACK ({dt:.2f}s)")
        continue

    llm_used += 1
    llm_ok = all(data.get(f) == exp[f] for f in FIELDS)
    llm_score += llm_ok
    diffs = {f: (data.get(f), exp[f]) for f in FIELDS if data.get(f) != exp[f]}
    print(f"{case['id']}: det={'OK' if det_ok else 'X '}  "
          f"llm={'OK' if llm_ok else 'X '} ({dt:.2f}s)  {diffs if diffs else ''}")

print(f"\nDeterministic: {det_score}/{len(cases)} match expected")
print(f"LLM:           {llm_score}/{llm_used} match expected (of {llm_used} answered, "
      f"{len(cases) - llm_used} fell back)")
