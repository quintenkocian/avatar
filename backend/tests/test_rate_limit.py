"""Tests for app.rate_limit — the per-conversation moving-window limiter."""

from __future__ import annotations

from app import rate_limit


def test_allows_up_to_limit_then_blocks():
    """20 hits per conversation pass; the 21st is rejected."""
    cid = "conv-limit-test"
    allowed = [rate_limit.check(cid) for _ in range(20)]
    assert all(allowed), "first 20 messages should be allowed"
    assert rate_limit.check(cid) is False, "21st message should be blocked"


def test_independent_windows_per_conversation():
    """Exhausting one conversation does not affect another."""
    a, b = "conv-a", "conv-b"
    for _ in range(20):
        rate_limit.check(a)
    assert rate_limit.check(a) is False
    # b is fresh and should still be allowed.
    assert rate_limit.check(b) is True


def test_reset_clears_state():
    cid = "conv-reset-test"
    for _ in range(20):
        rate_limit.check(cid)
    assert rate_limit.check(cid) is False
    rate_limit.reset()
    assert rate_limit.check(cid) is True
