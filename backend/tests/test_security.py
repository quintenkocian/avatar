"""Tests for app.security — admin session tokens, password check, cookies."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from itsdangerous import URLSafeTimedSerializer
from starlette.requests import Request

from app import security
from app.config import settings


def _make_request(cookies: dict[str, str] | None = None) -> Request:
    """Build a minimal Starlette Request carrying the given cookies."""
    cookies = cookies or {}
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = []
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode()))
    scope = {"type": "http", "headers": headers}
    return Request(scope)


def test_token_roundtrip():
    token = security.make_session_token()
    assert security.verify_session_token(token) is True


def test_token_rejects_tampered():
    token = security.make_session_token()
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    assert security.verify_session_token(tampered) is False


def test_token_rejects_empty_and_none():
    assert security.verify_session_token(None) is False
    assert security.verify_session_token("") is False


def test_token_rejects_foreign_signature():
    """A token signed with a different secret is rejected."""
    foreign = URLSafeTimedSerializer("not-the-secret", salt="avatar-admin-session")
    assert security.verify_session_token(foreign.dumps("admin")) is False


def test_token_rejects_wrong_payload():
    """A validly-signed token carrying a non-admin payload is still rejected.

    This proves the payload-equality guard (not just the signature) gates access:
    a token signed with the REAL secret + salt but with payload 'user' must fail.
    """
    legit = URLSafeTimedSerializer(
        settings.SESSION_SECRET, salt="avatar-admin-session"
    )
    assert security.verify_session_token(legit.dumps("user")) is False
    # Sanity: the same serializer with the admin payload IS accepted.
    assert security.verify_session_token(legit.dumps("admin")) is True


def test_token_expired(monkeypatch):
    """A token older than MAX_AGE is rejected.

    A negative max_age forces immediate expiry regardless of itsdangerous's
    1-second timestamp granularity (age 0 > -1 is True).
    """
    token = security.make_session_token()
    monkeypatch.setattr(security, "MAX_AGE_SECONDS", -1)
    assert security.verify_session_token(token) is False


def test_check_password_correct():
    assert security.check_password(settings.ADMIN_PASSWORD) is True


def test_check_password_wrong():
    assert security.check_password(settings.ADMIN_PASSWORD + "x") is False
    assert security.check_password("") is False


def test_check_password_fails_closed(monkeypatch):
    """With no ADMIN_PASSWORD configured, every candidate is rejected."""
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "")
    assert security.check_password("") is False
    assert security.check_password("anything") is False


def test_set_and_clear_cookie():
    resp = JSONResponse({"ok": True})
    security.set_session_cookie(resp)
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert settings.ADMIN_COOKIE_NAME.lower() in set_cookie
    assert "httponly" in set_cookie
    # CSRF hardening: the session cookie is SameSite=Lax.
    assert "samesite=lax" in set_cookie

    resp2 = JSONResponse({"ok": True})
    security.clear_session_cookie(resp2)
    cleared = resp2.headers.get("set-cookie", "").lower()
    assert settings.ADMIN_COOKIE_NAME.lower() in cleared
    assert "samesite=lax" in cleared


def test_cookie_secure_flag_follows_config(monkeypatch):
    """The Secure flag is present iff settings.COOKIE_SECURE is true."""
    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    resp = JSONResponse({"ok": True})
    security.set_session_cookie(resp)
    assert "secure" in resp.headers.get("set-cookie", "").lower()

    monkeypatch.setattr(settings, "COOKIE_SECURE", False)
    resp2 = JSONResponse({"ok": True})
    security.set_session_cookie(resp2)
    # No standalone `secure` attribute when not configured for HTTPS.
    parts = [p.strip().lower() for p in resp2.headers.get("set-cookie", "").split(";")]
    assert "secure" not in parts


def test_is_authenticated():
    token = security.make_session_token()
    req = _make_request({settings.ADMIN_COOKIE_NAME: token})
    assert security.is_authenticated(req) is True

    req_none = _make_request({})
    assert security.is_authenticated(req_none) is False


def test_require_admin_raises_without_cookie():
    req = _make_request({})
    with pytest.raises(HTTPException) as exc:
        security.require_admin(req)
    assert exc.value.status_code == 401


def test_require_admin_passes_with_cookie():
    token = security.make_session_token()
    req = _make_request({settings.ADMIN_COOKIE_NAME: token})
    # Should not raise.
    assert security.require_admin(req) is None
