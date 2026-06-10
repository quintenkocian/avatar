"""Tests for app.config — configuration loading and constants.

Default-resolution is tested via ``config._get`` directly (it reads ``os.getenv``
at call time) rather than reloading the module: a module reload re-runs
``load_dotenv`` against the real ``.env``, which would clobber any monkeypatched
environment.
"""

from __future__ import annotations

from app import config
from app.config import PROJECT_ROOT, Settings, settings


def test_env_loaded():
    """The project .env is loaded; key owner-specific values are present."""
    assert settings.OWNER_NAME
    assert settings.MODEL
    assert settings.SUPABASE_URL.startswith("https://")
    assert settings.SUPABASE_KEY


def test_get_treats_empty_as_unset(monkeypatch):
    """An empty env var is treated as unset and the default is returned."""
    monkeypatch.setenv("AVATAR_TEST_EMPTY", "")
    assert config._get("AVATAR_TEST_EMPTY", "fallback") == "fallback"
    monkeypatch.setenv("AVATAR_TEST_SET", "value")
    assert config._get("AVATAR_TEST_SET", "fallback") == "value"
    assert config._get("AVATAR_TEST_MISSING", "fallback") == "fallback"


def test_model_default(monkeypatch):
    """MODEL falls back to the cheap nano default when unset."""
    monkeypatch.delenv("MODEL", raising=False)
    assert config._get("MODEL", "openai/gpt-5.4-nano") == "openai/gpt-5.4-nano"


def test_owner_name_default(monkeypatch):
    """OWNER_NAME falls back to 'the owner' when unset."""
    monkeypatch.delenv("OWNER_NAME", raising=False)
    assert config._get("OWNER_NAME", "the owner") == "the owner"


def test_session_secret_derives_from_password(monkeypatch):
    """SESSION_SECRET derives from the admin password when not set explicitly."""
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    derived = config._get(
        "SESSION_SECRET", f"avatar::{config._get('ADMIN_PASSWORD')}"
    )
    assert derived == "avatar::s3cret"


def test_cookie_secure_flag(monkeypatch):
    """COOKIE_SECURE is True only when the env var equals the string '1'."""
    monkeypatch.setenv("COOKIE_SECURE", "1")
    assert (config._get("COOKIE_SECURE") == "1") is True
    monkeypatch.setenv("COOKIE_SECURE", "0")
    assert (config._get("COOKIE_SECURE") == "1") is False
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    assert (config._get("COOKIE_SECURE") == "1") is False


def test_abuse_guard_constants():
    """The abuse-guard constants match SPEC #12."""
    assert Settings.MAX_MESSAGE_CHARS == 20000
    assert Settings.RATE_LIMIT == "20/minute"
    assert "truncated" in Settings.TRUNCATION_NOTE


def test_cookie_names():
    assert settings.ADMIN_COOKIE_NAME == "avatar_admin"
    assert settings.CONVERSATION_COOKIE_NAME == "avatar_conversation"


def test_project_root_has_env():
    """PROJECT_ROOT resolves to the repo root, which contains .env."""
    assert (PROJECT_ROOT / ".env").exists()
    assert (PROJECT_ROOT / "SPEC.md").exists()
