"""Application configuration.

Loads the project-root ``.env`` and exposes a single ``settings`` object plus the
shared constants used across the backend. Every owner-specific value (model,
owner name, credentials) is read from the environment here and nowhere else, so
nothing is hardcoded.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# The repo root is two levels up from this file: backend/app/config.py -> repo/.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load the project-root .env, letting it override any pre-set process env so the
# file is the source of truth in local development.
load_dotenv(PROJECT_ROOT / ".env", override=True)


def _get(name: str, default: str = "") -> str:
    """Return an environment variable, treating an empty string as unset."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


class Settings:
    """Resolved configuration, read once at import time.

    All attributes are plain values (no network access happens here) so importing
    this module is cheap and side-effect free apart from reading ``.env``.
    """

    # --- LLM / OpenRouter ------------------------------------------------------
    OPENROUTER_API_KEY: str = _get("OPENROUTER_API_KEY")
    OPENROUTER_BASE_URL: str = _get(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    MODEL: str = _get("MODEL", "openai/gpt-5.4-nano")

    # --- Identity --------------------------------------------------------------
    OWNER_NAME: str = _get("OWNER_NAME", "the owner")

    # --- Admin auth ------------------------------------------------------------
    ADMIN_PASSWORD: str = _get("ADMIN_PASSWORD")
    # SESSION_SECRET signs the admin session cookie. If unset it derives from the
    # admin password so the app still works out of the box, but production should
    # set an explicit value (see README / SPEC setup notes).
    SESSION_SECRET: str = _get(
        "SESSION_SECRET", f"avatar::{_get('ADMIN_PASSWORD')}"
    )
    # Cookie is marked Secure only when COOKIE_SECURE == "1" (production HTTPS).
    COOKIE_SECURE: bool = _get("COOKIE_SECURE") == "1"

    # --- Pushover (optional) ---------------------------------------------------
    PUSHOVER_USER: str = _get("PUSHOVER_USER")
    PUSHOVER_TOKEN: str = _get("PUSHOVER_TOKEN")

    # --- Supabase --------------------------------------------------------------
    SUPABASE_URL: str = _get("SUPABASE_URL")
    SUPABASE_KEY: str = _get("SUPABASE_KEY")

    # --- Paths -----------------------------------------------------------------
    KNOWLEDGE_DIR: Path = Path(
        _get("KNOWLEDGE_DIR", str(PROJECT_ROOT / "knowledge"))
    )
    STATIC_DIR: Path = Path(
        _get("STATIC_DIR", str(PROJECT_ROOT / "frontend" / "dist"))
    )

    # --- Abuse guards / limits -------------------------------------------------
    MAX_MESSAGE_CHARS: int = 20000
    TRUNCATION_NOTE: str = (
        "\n\n[...message truncated as it's too long; ask the visitor to send "
        "something more concise]"
    )
    RATE_LIMIT: str = "20/minute"

    # --- Cookie names ----------------------------------------------------------
    ADMIN_COOKIE_NAME: str = "avatar_admin"
    CONVERSATION_COOKIE_NAME: str = "avatar_conversation"


settings = Settings()

__all__ = ["settings", "Settings", "PROJECT_ROOT"]
