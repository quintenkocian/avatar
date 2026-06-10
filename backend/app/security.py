"""Admin session security.

A signed, timestamped session token is stored in the ``avatar_admin`` httpOnly
cookie. ``require_admin`` is a FastAPI dependency that guards every ``/admin/*``
data route (but not the static ``/admin`` page nor ``/admin/login``).
"""

from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

# Tokens are valid for 7 days.
MAX_AGE_SECONDS = 7 * 24 * 60 * 60
_SALT = "avatar-admin-session"
_TOKEN_PAYLOAD = "admin"

_serializer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt=_SALT)


def make_session_token() -> str:
    """Create a fresh signed session token."""
    return _serializer.dumps(_TOKEN_PAYLOAD)


def verify_session_token(token: str | None) -> bool:
    """Return True if ``token`` is a valid, unexpired session token."""
    if not token:
        return False
    try:
        payload = _serializer.loads(token, max_age=MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return payload == _TOKEN_PAYLOAD


def check_password(candidate: str) -> bool:
    """Constant-time comparison of a candidate password against ADMIN_PASSWORD."""
    if not settings.ADMIN_PASSWORD:
        # No password configured => no admin access (fail closed).
        return False
    return hmac.compare_digest(candidate, settings.ADMIN_PASSWORD)


def set_session_cookie(response: Response) -> None:
    """Attach a fresh signed session cookie to ``response``."""
    response.set_cookie(
        key=settings.ADMIN_COOKIE_NAME,
        value=make_session_token(),
        max_age=MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie from the client."""
    response.delete_cookie(
        key=settings.ADMIN_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )


def is_authenticated(request: Request) -> bool:
    """Return True if the request carries a valid admin session cookie."""
    token = request.cookies.get(settings.ADMIN_COOKIE_NAME)
    return verify_session_token(token)


def require_admin(request: Request) -> None:
    """FastAPI dependency: raise 401 unless a valid admin session is present."""
    # Imported here to keep the module importable without FastAPI's HTTPException
    # at the top level being a problem for AST checks (it is fine either way).
    from fastapi import HTTPException

    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="admin authentication required")


__all__ = [
    "MAX_AGE_SECONDS",
    "make_session_token",
    "verify_session_token",
    "check_password",
    "set_session_cookie",
    "clear_session_cookie",
    "is_authenticated",
    "require_admin",
]
