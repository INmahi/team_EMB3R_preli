# RUNBOOK — QueueStorm Investigator

Copy-paste steps to run, test, and deploy the service. A stranger should be able to bring it
up from a clean clone with only this file.

## 1. Run locally (no Docker)

```bash
git clone https://github.com/INmahi/team_EMB3R_preli.git
cd team_EMB3R_preli

python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Unix/macOS:         source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify (second terminal):
```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @samples/sample_input.json
```

## 2. Run tests

```bash
pip install -r requirements.txt
pytest -q          # 23 tests: reasoning, safety, API contract
```

## 3. Run with Docker

```bash
docker build -t queuestorm .
docker images queuestorm                      # confirm size (well under 1GB)
docker run --rm -p 8000:8000 --env-file .env queuestorm
```
- `.env` is optional. With no env file the service runs in **deterministic mode** (LLM off).
- The container binds `0.0.0.0` and reads `$PORT` (default 8000).
- `/health` is ready within a few seconds of start (gate is 60s).

## 4. Enable the optional LLM (optional)

The service scores fully without this. To turn on LLM-polished text, set these env vars
(in `.env` locally, or the hosting dashboard in production — never commit real keys):

```env
LLM_ENABLED=true
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=<your-key>
LLM_TIMEOUT=8
```
Other providers (same protocol): Google Gemini (`.../v1beta/openai`, `gemini-2.0-flash`),
OpenRouter (`https://openrouter.ai/api/v1`, a `:free` model). On any LLM error/timeout the
service silently falls back to deterministic text.

## 5. Deploy to Railway (primary submission path)

1. Push the repo to GitHub.
2. railway.app → **New Project → Deploy from GitHub repo** → select this repo.
3. Railway reads `railway.json` / `Dockerfile` and builds the image.
4. (Optional) **Variables** tab → add LLM vars from step 4 if using the LLM.
5. **Settings → Networking → Generate Domain** → public HTTPS URL (the submitted base URL).
6. Confirm the service does not sleep/scale-to-zero during the evaluation window.
7. Verify from outside:
   ```bash
   curl https://<your-domain>/health
   curl -X POST https://<your-domain>/analyze-ticket \
     -H "Content-Type: application/json" -d @samples/sample_input.json
   ```

## 6. Submission

- **Path A (preferred):** the live Railway URL above.
- **Path B (fallback):** `docker build` / `docker run` commands in section 3.
- **Path C (fallback):** this runbook.
- Repo: private is fine — add organizer **`bipulhf`** with **read** access before the deadline.
- Required in repo: `README.md` (incl. MODELS), `requirements.txt`, `.env.example`,
  `samples/sample_output.json`. **No real secrets / no real customer or payment data.**
- ⏰ You **cannot push after the deadline** — finish, deploy, and verify with margin.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `curl: connection refused` | Ensure bound to `0.0.0.0` (the Dockerfile/uvicorn cmd already do). |
| Port already in use | Use another host port: `docker run -p 8080:8000 ...`, curl `:8080`. |
| Container exits immediately | `docker logs <id>` — usually a typo in an env var. |
| 400 on a valid-looking request | `ticket_id` and `complaint` are required; check JSON validity. |
| LLM not taking effect | `LLM_ENABLED=true` AND a non-empty `LLM_API_KEY` are both required. |
