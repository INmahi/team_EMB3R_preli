"""Generate samples/sample_output.json from a representative input.

Run: python scripts/gen_sample_output.py
This produces the required 'sample output file' deliverable. Replace the input
with a case from QueueStorm_Preli_Sample_Cases.json when that file is available.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

SAMPLE_INPUT = {
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number around 2pm today. Please help me get it back.",
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


def main() -> None:
    output = client.post("/analyze-ticket", json=SAMPLE_INPUT).json()
    os.makedirs("samples", exist_ok=True)
    with open("samples/sample_output.json", "w", encoding="utf-8") as f:
        json.dump({"input": SAMPLE_INPUT, "output": output}, f, indent=2, ensure_ascii=False)
    print("Wrote samples/sample_output.json (severity=%s)" % output["severity"])


if __name__ == "__main__":
    main()
