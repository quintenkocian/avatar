"""Live integration tests — real model + real Supabase.

Marked ``@pytest.mark.llm`` so the default hermetic run can skip them
(``-m "not llm"``). They use the configured ``MODEL`` (kept at
``openai/gpt-5.4-nano`` for tests, per SPEC) and write to Supabase, deleting
every conversation they create.

Run with:  uv run pytest -m llm -q
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app import agent, db
from app.config import settings
from conftest import parse_sse

pytestmark = pytest.mark.llm

_HAVE_LLM = bool(settings.OPENROUTER_API_KEY)
_HAVE_DB = bool(settings.SUPABASE_URL and settings.SUPABASE_KEY)


async def _collect(task: str, owner: str) -> list[dict]:
    pieces: list[dict] = []
    async for piece in agent.stream_reply(task, owner):
        pieces.append(piece)
    return pieces


@pytest.mark.skipif(not _HAVE_LLM, reason="OPENROUTER_API_KEY not configured")
def test_stream_reply_real_model():
    """The real agent yields streamed text for a simple greeting."""
    task = (
        "Here is the full conversation so far. Respond as the Avatar to the "
        "latest Visitor message.\n\nVisitor: Say hello in one short sentence."
    )
    pieces = asyncio.run(_collect(task, settings.OWNER_NAME))
    types = {p["type"] for p in pieces}
    assert "token" in types, f"expected token pieces, got {types}"
    text = "".join(p.get("text", "") for p in pieces if p["type"] == "token")
    assert text.strip(), "expected non-empty streamed text"
    assert not any(p["type"] == "error" for p in pieces)


@pytest.mark.skipif(
    not (_HAVE_LLM and _HAVE_DB), reason="LLM or Supabase not configured"
)
def test_chat_endpoint_persists_and_cleans_up(client):
    """A real /api/chat call persists visitor + avatar rows; we then delete them."""
    # conversation_id is a uuid column, so use a bare uuid4 (cleaned up below).
    cid = str(uuid.uuid4())
    try:
        resp = client.post(
            "/api/chat",
            json={
                "conversation_id": cid,
                "name": "Test Visitor",
                "message": "In one short sentence, what city are you from?",
            },
        )
        assert resp.status_code == 200
        frames = parse_sse(resp.text)
        assert frames[0]["type"] == "start"
        assert frames[-1]["type"] == "done"
        assert frames[-1]["message_id"] is not None

        rows = db.get_conversation(cid)
        roles = [r["role"] for r in rows]
        assert "visitor" in roles
        assert "avatar" in roles
        # The visitor's stored row carries the provided name.
        assert any(r.get("conversation_name") == "Test Visitor" for r in rows)
    finally:
        db.delete_conversation(cid)
        # Confirm cleanup.
        assert db.get_conversation(cid) == []
