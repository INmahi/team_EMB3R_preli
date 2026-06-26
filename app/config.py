"""Runtime configuration, loaded from environment variables only.

No secrets are hard-coded here. Everything the service needs at runtime is read
from the environment so the same image works locally, in Docker, and on Railway.
"""
from __future__ import annotations

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


class Settings:
    """Process-wide settings resolved once at import time."""

    # Server. Railway injects PORT; bind 0.0.0.0 so the container is reachable.
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Optional LLM layer. OFF by default -> the service is fully functional,
    # fast, and free without any API key. When enabled, the LLM only *refines*
    # text fields; the deterministic engine and safety filter always run.
    LLM_ENABLED: bool = _as_bool(os.getenv("LLM_ENABLED"), default=False)
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    # Keep well under the 30s per-request hard limit; fall back on timeout.
    LLM_TIMEOUT: float = _as_float(os.getenv("LLM_TIMEOUT"), default=8.0)

    @classmethod
    def llm_active(cls) -> bool:
        """LLM is usable only if explicitly enabled AND a key is present."""
        return cls.LLM_ENABLED and bool(cls.LLM_API_KEY)


settings = Settings()
