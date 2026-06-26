"""One raw LLM call that prints the real status/error (no fallback swallowing)."""
import os
import time

import httpx

BASE = os.environ["LLM_BASE_URL"].rstrip("/")
KEY = os.environ["LLM_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "gemini-2.0-flash")

url = BASE + "/chat/completions"
payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Reply with strict JSON: {\"ok\": true}"}],
    "response_format": {"type": "json_object"},
}
headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

print(f"POST {url}\nmodel={MODEL}\n")
t0 = time.time()
try:
    r = httpx.post(url, json=payload, headers=headers, timeout=30)
    print(f"status={r.status_code} ({time.time()-t0:.2f}s)")
    print("body:", r.text[:800])
except Exception as e:
    print(f"EXCEPTION after {time.time()-t0:.2f}s: {type(e).__name__}: {e}")
