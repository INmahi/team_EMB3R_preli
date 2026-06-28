"""Runtime configuration, loaded from environment variables only.

No secrets are hard-coded here. Everything the service needs at runtime is read
from the environment so the same image works locally, in Docker, and on Railway.

LLM providers
-------------
Two ways to configure the LLM layer:

1. Multi-provider (recommended) — set `LLM_PROVIDERS` to a JSON array. Each entry:
     {"name": "...", "base_url": "...", "model": "...", "api_key": "...", "timeout": 8}
   The service load-balances across them (round-robin) and fails over on 429 /
   5xx / timeout, so no single free key gets rate-limited.

2. Single provider (legacy) — set LLM_BASE_URL / LLM_MODEL / LLM_API_KEY / LLM_TIMEOUT.
   Used automatically if LLM_PROVIDERS is not set.
"""
from __future__ import annotations

import json
import os


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _load_providers() -> list[dict]:
    """Build the provider list from LLM_PROVIDERS (JSON), else the legacy vars."""
    providers: list[dict] = []

    raw = os.getenv("LLM_PROVIDERS")
    if raw:
        try:
            for p in json.loads(raw):
                if p.get("api_key") and p.get("base_url") and p.get("model"):
                    providers.append({
                        "name": str(p.get("name") or p["base_url"]),
                        "base_url": str(p["base_url"]).rstrip("/"),
                        "model": str(p["model"]),
                        "api_key": str(p["api_key"]),
                        "timeout": _as_float(str(p.get("timeout", 8)), 8.0),
                    })
        except Exception:
            providers = []  # malformed -> ignore, fall back to legacy/none

    # Legacy single-provider fallback.
    if not providers:
        key = os.getenv("LLM_API_KEY", "")
        if key:
            providers.append({
                "name": "default",
                "base_url": os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
                "model": os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
                "api_key": key,
                "timeout": _as_float(os.getenv("LLM_TIMEOUT"), 8.0),
            })
    return providers


class Settings:
    """Process-wide settings resolved once at import time."""

    # Server. Railway injects PORT; bind 0.0.0.0 so the container is reachable.
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # LLM layer. When enabled with >=1 provider, the LLM performs the full analysis;
    # the deterministic engine remains the fallback + safety guardrail.
    LLM_ENABLED: bool = _as_bool(os.getenv("LLM_ENABLED"), default=False)
    PROVIDERS: list[dict] = _load_providers()

    # Seconds a provider is skipped after a 429 / overload, so we stop hammering it.
    PROVIDER_COOLDOWN: float = _as_float(os.getenv("LLM_PROVIDER_COOLDOWN"), 30.0)

    def llm_active(self) -> bool:
        """LLM is usable only if enabled AND at least one provider is configured."""
        return self.LLM_ENABLED and len(self.PROVIDERS) > 0


settings = Settings()
