"""Per-conversation rate limiting.

A moving-window limiter from the ``limits`` package, held in memory per process.
Each ``conversation_id`` is limited to ``settings.RATE_LIMIT`` (20/minute). This
is checked BEFORE any model call in the chat and instant routes; on failure the
route returns HTTP 429 and no LLM call is made.

In-memory state is sufficient here: OpenRouter caps overall spend and a browser's
requests stick to one machine (see SPEC Q&A #12).
"""

from __future__ import annotations

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from .config import settings

_storage = MemoryStorage()
_limiter = MovingWindowRateLimiter(_storage)
_rate = parse(settings.RATE_LIMIT)
_login_rate = parse(settings.LOGIN_RATE_LIMIT)

# Namespaces so keys never collide across the different limited surfaces.
_NAMESPACE = "chat"
_LOGIN_NAMESPACE = "login"


def check(conversation_id: str) -> bool:
    """Consume one unit for ``conversation_id``. Return True if allowed.

    ``hit`` both tests and consumes the window in one call: it returns False once
    the limit for the current window is exceeded.
    """
    return _limiter.hit(_rate, _NAMESPACE, conversation_id)


def login_check(client_ip: str) -> bool:
    """Consume one failed-login unit for ``client_ip``. Return True if allowed.

    Per-IP keying means an attacker only ever locks out their own IP. Successful
    logins are never counted (the caller only records failures), so a legitimate
    owner is never throttled.
    """
    return _limiter.hit(_login_rate, _LOGIN_NAMESPACE, client_ip or "unknown")


def reset() -> None:
    """Clear all rate-limit state (used by tests)."""
    _storage.reset()


__all__ = ["check", "login_check", "reset"]
