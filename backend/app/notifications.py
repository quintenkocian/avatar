"""Pushover notifications: human-in-the-loop pings and backend-error alerts.

All pushes are high priority (``priority: 1``) so they bypass quiet hours. The
human-in-the-loop ping uses the ``bugle`` sound; backend-error alerts use
``gamelan``. Error alerts are debounced per category (a few per hour) so a flood
can't spam notifications or drain the Pushover quota — EXCEPT failed-login
alerts, which are intentionally un-debounced (bounded instead by the per-IP login
throttle) so the owner sees each attempt.

Every send has a short timeout and fails softly: a slow or unreachable Pushover
can never hang a chat turn or a request.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

from .config import settings

logger = logging.getLogger("avatar.notifications")

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
_TIMEOUT_SECONDS = 8

# Debounce: at most this many error alerts per category per window.
_ERROR_WINDOW_SECONDS = 3600
_ERROR_MAX_PER_WINDOW = 3
_error_history: dict[str, list[float]] = {}
_lock = threading.Lock()


def _send(message: str, *, sound: str, priority: int = 1, title: str | None = None) -> bool:
    """POST a notification to Pushover. Returns True on a 2xx, else False.

    Never raises: missing credentials or a network error are logged and swallowed
    so a notification failure can't break the request that triggered it.
    """
    if not settings.PUSHOVER_USER or not settings.PUSHOVER_TOKEN:
        logger.warning(
            "Pushover credentials missing; skipping push. Message was: %s", message
        )
        return False
    data = {
        "user": settings.PUSHOVER_USER,
        "token": settings.PUSHOVER_TOKEN,
        "message": message,
        "priority": priority,
        "sound": sound,
    }
    if title:
        data["title"] = title
    try:
        resp = requests.post(PUSHOVER_URL, data=data, timeout=_TIMEOUT_SECONDS)
        if resp.status_code >= 400:
            logger.warning("Pushover returned %s for message: %s", resp.status_code, message)
            return False
        return True
    except requests.RequestException as exc:  # pragma: no cover - network error
        logger.warning("Pushover request failed: %s", exc)
        return False


def push_human(message: str) -> str:
    """Notify the human operator (the digital twin's human). High priority, bugle.

    Returns a short status string suitable for handing back to the agent's tool.
    """
    ok = _send(message, sound="bugle", priority=1, title="Avatar — someone needs you")
    if not settings.PUSHOVER_USER or not settings.PUSHOVER_TOKEN:
        return "Push notification skipped (operator notifications not configured)."
    if ok:
        return "Message pushed to the human operator."
    return "Push notification could not be delivered right now."


def _debounced(category: str) -> bool:
    """Return True if an alert in ``category`` is allowed under the rate window."""
    now = time.monotonic()
    with _lock:
        history = [t for t in _error_history.get(category, []) if now - t < _ERROR_WINDOW_SECONDS]
        if len(history) >= _ERROR_MAX_PER_WINDOW:
            _error_history[category] = history
            return False
        history.append(now)
        _error_history[category] = history
        return True


def push_error(category: str, detail: str) -> None:
    """Alert the owner about a backend error. Debounced per category, gamelan sound.

    ``category`` groups related errors (e.g. ``"chat"``, ``"server"``) so a burst
    of the same failure collapses to a few alerts per hour.
    """
    if not _debounced(category):
        logger.info("Suppressed debounced error alert for category %s", category)
        return
    _send(
        f"[{category}] {detail}"[:900],
        sound="gamelan",
        priority=1,
        title="Avatar — backend error",
    )


def push_login_failure(client_ip: str) -> None:
    """Alert the owner about a failed admin login. NOT debounced (bounded by throttle)."""
    _send(
        f"Failed admin login attempt from {client_ip}.",
        sound="gamelan",
        priority=1,
        title="Avatar — failed admin login",
    )


def reset() -> None:
    """Clear debounce state (used by tests)."""
    with _lock:
        _error_history.clear()


__all__ = [
    "PUSHOVER_URL",
    "push_human",
    "push_error",
    "push_login_failure",
    "reset",
]
