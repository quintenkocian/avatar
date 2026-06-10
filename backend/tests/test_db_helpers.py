"""Tests for the pure (network-free) helpers in app.db.

The read/write functions hit Supabase, but the name/initials helpers are pure
and worth exercising directly.
"""

from __future__ import annotations

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
