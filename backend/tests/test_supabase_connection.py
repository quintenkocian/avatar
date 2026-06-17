"""Connectivity check for the Supabase messages table.

Verifies that the credentials in the project-root .env work and that the
expected table is reachable via the Data API using the secret key.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from supabase import Client, create_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=True)

EXPECTED_COLUMNS = {
    "id",
    "conversation_id",
    "conversation_name",
    "role",
    "content",
    "tool_calls",
    "needs_attention",
    "read",
    "created_at",
}


@pytest.fixture(scope="module")
def client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def test_env_present():
    assert os.environ.get("SUPABASE_URL", "").startswith("https://")
    assert os.environ.get("SUPABASE_KEY", "").startswith("sb_secret_")


def test_messages_table_reachable(client: Client):
    """The table is queryable through the Data API with the secret key."""
    result = client.table("messages").select("*").limit(1).execute()
    assert isinstance(result.data, list)


def test_insert_and_delete_roundtrip(client: Client):
    """A full write/read/delete cycle works and stores the expected columns."""
    conversation_id = "00000000-0000-0000-0000-000000000000"
    inserted = (
        client.table("messages")
        .insert(
            {
                "conversation_id": conversation_id,
                "role": "visitor",
                "content": "connectivity test",
            }
        )
        .execute()
    )
    row = inserted.data[0]
    try:
        assert EXPECTED_COLUMNS.issubset(row.keys())
        assert row["role"] == "visitor"
        assert row["needs_attention"] is False
        assert row["read"] is False
    finally:
        client.table("messages").delete().eq("id", row["id"]).execute()


# --- MORE: archive / settings / faq tables -----------------------------------


def test_archive_table_reachable_and_shaped(client: Client):
    """The archive table mirrors messages and supports the same write/read cycle."""
    conversation_id = "00000000-0000-0000-0000-000000000000"
    inserted = (
        client.table("archive")
        .insert(
            {
                "conversation_id": conversation_id,
                "role": "visitor",
                "content": "archive connectivity test",
            }
        )
        .execute()
    )
    row = inserted.data[0]
    try:
        assert EXPECTED_COLUMNS.issubset(row.keys())
    finally:
        client.table("archive").delete().eq("id", row["id"]).execute()


def test_settings_singleton_row(client: Client):
    """The settings table has its single pinned row (id=1) with the text column."""
    result = (
        client.table("settings")
        .select("id,additional_instructions")
        .eq("id", 1)
        .execute()
    )
    assert result.data, "expected the seeded settings row id=1 (run the MORE SQL)"
    assert "additional_instructions" in result.data[0]


def test_faq_table_reachable_and_shaped(client: Client):
    """The faq table is reachable and carries id/concise/question/answer."""
    result = client.table("faq").select("*").order("id").limit(1).execute()
    assert isinstance(result.data, list)
    if result.data:
        assert {"id", "concise", "question", "answer"}.issubset(
            result.data[0].keys()
        )
