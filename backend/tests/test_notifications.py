"""Tests for app.notifications — Pushover priority/sounds + error debouncing."""

from __future__ import annotations

import pytest

from app import notifications


@pytest.fixture(autouse=True)
def _reset_notifications():
    notifications.reset()
    yield
    notifications.reset()


class _FakeResp:
    def __init__(self, status_code=200):
        self.status_code = status_code


def test_push_human_uses_bugle_high_priority(monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured.update(data)
        return _FakeResp(200)

    monkeypatch.setattr(notifications.settings, "PUSHOVER_USER", "u")
    monkeypatch.setattr(notifications.settings, "PUSHOVER_TOKEN", "t")
    monkeypatch.setattr(notifications.requests, "post", fake_post)

    out = notifications.push_human("Visitor wants to connect")
    assert captured["sound"] == "bugle"
    assert captured["priority"] == 1
    assert "pushed" in out.lower()


def test_push_human_missing_creds_is_soft(monkeypatch):
    monkeypatch.setattr(notifications.settings, "PUSHOVER_USER", "")
    monkeypatch.setattr(notifications.settings, "PUSHOVER_TOKEN", "")
    out = notifications.push_human("hi")
    assert "skipped" in out.lower()


def test_error_alerts_debounced_per_category(monkeypatch):
    sent = []

    def fake_post(url, data=None, timeout=None):
        sent.append(data)
        return _FakeResp(200)

    monkeypatch.setattr(notifications.settings, "PUSHOVER_USER", "u")
    monkeypatch.setattr(notifications.settings, "PUSHOVER_TOKEN", "t")
    monkeypatch.setattr(notifications.requests, "post", fake_post)

    for _ in range(10):
        notifications.push_error("chat", "OpenRouter rate limit")
    # At most _ERROR_MAX_PER_WINDOW within the window.
    assert len(sent) == notifications._ERROR_MAX_PER_WINDOW
    assert all(d["sound"] == "gamelan" for d in sent)


def test_login_failure_not_debounced(monkeypatch):
    sent = []

    def fake_post(url, data=None, timeout=None):
        sent.append(data)
        return _FakeResp(200)

    monkeypatch.setattr(notifications.settings, "PUSHOVER_USER", "u")
    monkeypatch.setattr(notifications.settings, "PUSHOVER_TOKEN", "t")
    monkeypatch.setattr(notifications.requests, "post", fake_post)

    for _ in range(6):
        notifications.push_login_failure("1.2.3.4")
    # Every attempt fires (bounded elsewhere by the per-IP login throttle).
    assert len(sent) == 6
    assert all(d["sound"] == "gamelan" for d in sent)


def test_send_network_error_is_soft(monkeypatch):
    def boom(url, data=None, timeout=None):
        raise notifications.requests.RequestException("down")

    monkeypatch.setattr(notifications.settings, "PUSHOVER_USER", "u")
    monkeypatch.setattr(notifications.settings, "PUSHOVER_TOKEN", "t")
    monkeypatch.setattr(notifications.requests, "post", boom)
    # Must not raise.
    out = notifications.push_human("hi")
    assert "could not be delivered" in out.lower()
