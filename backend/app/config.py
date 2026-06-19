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
    # Hard per-reply output ceiling (ModelSettings.max_tokens). A graceful
    # "kept it brief" note is appended on the rare truncation.
    MODEL_MAX_TOKENS: int = int(_get("MODEL_MAX_TOKENS", "2000"))
    # Per-turn transcript budget (characters). The most recent messages within
    # this budget are sent to the model; older lines are dropped with a note.
    # The full history is still stored in the database.
    TRANSCRIPT_CHAR_BUDGET: int = int(_get("TRANSCRIPT_CHAR_BUDGET", "24000"))
    # Web-fetch MCP server. Command defaults to ``uvx mcp-server-fetch`` locally;
    # the Docker image pre-installs the tool and sets FETCH_MCP_COMMAND so no
    # download happens on the first request. Empty FETCH_MCP_COMMAND disables it.
    FETCH_MCP_COMMAND: str = _get("FETCH_MCP_COMMAND", "uvx")
    FETCH_MCP_ARGS: str = _get("FETCH_MCP_ARGS", "mcp-server-fetch")

    # --- Identity --------------------------------------------------------------
    OWNER_NAME: str = _get("OWNER_NAME", "the owner")

    # Optional explicit public base URL (e.g. "https://avatar.example.com") used
    # to build absolute og:image / og:url tags on the visitor page. When unset,
    # the base is derived per-request from the Host / X-Forwarded-Proto headers,
    # which is correct for both the *.fly.dev host and a custom domain.
    PUBLIC_BASE_URL: str = _get("PUBLIC_BASE_URL")

    # --- Admin auth ------------------------------------------------------------
    ADMIN_PASSWORD: str = _get("ADMIN_PASSWORD")
    # SESSION_SECRET signs the admin session cookie. If unset it derives from the
    # admin password. The app refuses to start without ADMIN_PASSWORD (see
    # ``require_admin_password``), so this default is never the public constant
    # ``avatar::`` that would otherwise allow cookie forgery.
    SESSION_SECRET: str = _get(
        "SESSION_SECRET", f"avatar::{_get('ADMIN_PASSWORD')}"
    )
    # Cookie is marked Secure only when COOKIE_SECURE == "1" (production HTTPS).
    COOKIE_SECURE: bool = _get("COOKIE_SECURE") == "1"
    # Failed admin logins are throttled per client IP to blunt online brute force.
    LOGIN_RATE_LIMIT: str = _get("LOGIN_RATE_LIMIT", "5/minute")

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


def require_admin_password() -> None:
    """Fail closed: raise unless an admin password is configured.

    Called at application startup. Without ``ADMIN_PASSWORD`` set, the admin
    surface would accept an empty password AND the session-signing secret would
    degrade to a public constant, allowing cookie forgery. We refuse to start
    rather than run insecurely. (Tests and the connectivity check load ``.env``,
    which sets it.)
    """
    if not settings.ADMIN_PASSWORD:
        raise RuntimeError(
            "ADMIN_PASSWORD is not set. The Avatar backend refuses to start "
            "without an admin password (it protects the admin dashboard and "
            "signs the session cookie). Set ADMIN_PASSWORD in the project-root "
            ".env and restart."
        )


__all__ = ["settings", "Settings", "PROJECT_ROOT", "require_admin_password"]
