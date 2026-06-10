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

# Namespace so keys never collide with anything else stored in the limiter.
_NAMESPACE = "chat"


def check(conversation_id: str) -> bool:
    """Consume one unit for ``conversation_id``. Return True if allowed.

    ``hit`` both tests and consumes the window in one call: it returns False once
    the limit for the current window is exceeded.
    """
    return _limiter.hit(_rate, _NAMESPACE, conversation_id)


def reset() -> None:
    """Clear all rate-limit state (used by tests)."""
    _storage.reset()


__all__ = ["check", "reset"]
