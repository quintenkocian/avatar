"""Tests for the pure helpers in app.main (no I/O)."""

from __future__ import annotations

import json

from app import main
from app.config import settings


def test_clamp_short_message_unchanged():
    msg = "a short message"
    assert main._clamp_message(msg) == msg


def test_clamp_truncates_and_appends_note():
    msg = "x" * (settings.MAX_MESSAGE_CHARS + 500)
    clamped = main._clamp_message(msg)
    assert clamped.startswith("x" * settings.MAX_MESSAGE_CHARS)
    assert clamped.endswith(settings.TRUNCATION_NOTE)
    # The stored/sent text is the clamped body plus the note.
    assert len(clamped) == settings.MAX_MESSAGE_CHARS + len(settings.TRUNCATION_NOTE)


def test_clamp_exactly_at_limit_unchanged():
    msg = "y" * settings.MAX_MESSAGE_CHARS
    assert main._clamp_message(msg) == msg


def test_qn_regex_matches():
    assert main._QN_RE.match("Q1")
    assert main._QN_RE.match("q12")
    assert main._QN_RE.match("Q9")
    assert main._QN_RE.match("Q01")


def test_qn_regex_rejects():
    assert main._QN_RE.match("Q") is None
    assert main._QN_RE.match("Q123") is None  # 3 digits
    assert main._QN_RE.match("hello") is None
    assert main._QN_RE.match("Q1 please") is None


def test_name_to_store_first_name_sticks():
    # No existing name and a provided name => store it.
    assert main._name_to_store("Ada", []) == "Ada"
    # Existing name present => do not overwrite.
    rows = [{"conversation_name": "Ada"}]
    assert main._name_to_store("Grace", rows) is None
    # No provided name => nothing to store.
    assert main._name_to_store("", []) is None
    assert main._name_to_store(None, []) is None
    # Whitespace-only is treated as empty.
    assert main._name_to_store("   ", []) is None


def test_sse_frame_format():
    frame = main._sse({"type": "token", "text": "hi"})
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    payload = json.loads(frame[len("data: "):].strip())
    assert payload == {"type": "token", "text": "hi"}
