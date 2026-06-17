"""Tests for the pure (network-free) helpers in app.db.

The read/write functions hit Supabase, but the name/initials helpers are pure
and worth exercising directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app import db


def test_initials_two_names():
    assert db._initials("Ada Lovelace") == "AL"


def test_initials_single_name():
    assert db._initials("Ada") == "AD"
    assert db._initials("ada") == "AD"


def test_initials_three_parts_uses_first_and_last():
    assert db._initials("Grace Brewster Hopper") == "GH"


def test_initials_empty_and_none():
    assert db._initials(None) == "?"
    assert db._initials("") == "?"
    assert db._initials("   ") == "?"


def test_name_from_rows_first_nonempty():
    rows = [
        {"conversation_name": None},
        {"conversation_name": ""},
        {"conversation_name": "Ada"},
        {"conversation_name": "Grace"},
    ]
    assert db._name_from_rows(rows) == "Ada"
    assert db.conversation_name_from_rows(rows) == "Ada"


def test_name_from_rows_none_when_absent():
    rows = [{"conversation_name": None}, {"role": "avatar"}]
    assert db._name_from_rows(rows) is None
    assert db.conversation_name_from_rows([]) is None


# --- MORE: portable-row projection -------------------------------------------


def test_portable_rows_drops_id_keeps_created_at():
    rows = [
        {
            "id": 42,
            "conversation_id": "c1",
            "conversation_name": "Ada",
            "role": "visitor",
            "content": "hi",
            "tool_calls": None,
            "needs_attention": False,
            "read": True,
            "created_at": "2026-01-01T00:00:01Z",
            "extra": "ignored",
        }
    ]
    out = db._portable_rows(rows)
    assert "id" not in out[0]
    assert "extra" not in out[0]
    assert out[0]["created_at"] == "2026-01-01T00:00:01Z"
    assert out[0]["conversation_id"] == "c1"


# --- MORE: timestamp parsing + inactivity grouping ---------------------------


def test_parse_ts_handles_z_and_offset():
    a = db._parse_ts("2026-01-01T00:00:00Z")
    b = db._parse_ts("2026-01-01T00:00:00+00:00")
    assert a == b
    assert a.tzinfo is not None


def test_parse_ts_handles_space_separator():
    dt = db._parse_ts("2026-01-01 12:30:00+00:00")
    assert dt is not None
    assert dt.hour == 12


def test_parse_ts_invalid_returns_none():
    assert db._parse_ts("") is None
    assert db._parse_ts("not-a-date") is None


def test_latest_at_by_conversation():
    rows = [
        {"conversation_id": "c1", "created_at": "2026-01-01T00:00:01Z"},
        {"conversation_id": "c1", "created_at": "2026-01-03T00:00:01Z"},
        {"conversation_id": "c2", "created_at": "2026-01-02T00:00:01Z"},
    ]
    latest = db._latest_at_by_conversation(rows)
    assert latest["c1"] == "2026-01-03T00:00:01Z"
    assert latest["c2"] == "2026-01-02T00:00:01Z"


# --- MORE: faq normalisation -------------------------------------------------


def test_normalise_faq_coerces_types():
    row = db._normalise_faq(
        {"id": "5", "concise": None, "question": "Q?", "answer": "A."}
    )
    assert row == {"id": 5, "concise": "", "question": "Q?", "answer": "A."}
