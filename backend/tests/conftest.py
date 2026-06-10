"""Shared pytest fixtures for the Avatar backend suite.

The hermetic tests never touch the network: the Supabase data-access functions
(``app.db.*``) and the agent stream (``app.agent.stream_reply``) are replaced
with in-memory fakes. The FastAPI route handlers reference these as module
attributes at call time, so monkeypatching the module attribute is sufficient.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app import db, rate_limit, security
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Clear the in-memory limiter before and after every test."""
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture
def client() -> TestClient:
    """An unauthenticated TestClient against the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def admin_client(client: TestClient) -> TestClient:
    """A TestClient carrying a valid admin session cookie.

    The cookie is minted directly via the security module so the fixture does not
    depend on the login route (which is tested separately).
    """
    token = security.make_session_token()
    client.cookies.set(settings.ADMIN_COOKIE_NAME, token)
    return client


class FakeDB:
    """In-memory stand-in for the Supabase data layer.

    Records calls and returns plausible rows so route logic can be exercised
    without a database. Install it with :func:`install_fake_db`.
    """

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._next_id = 1
        self.calls: list[tuple[str, tuple, dict]] = []
        self.conversation: list[dict] = []
        self.inbox: list[dict] = []
        self.opened: list[str] = []
        self.resolved: list[str] = []

    # -- writes ---------------------------------------------------------------
    def insert_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        conversation_name: str | None = None,
        tool_calls: Any | None = None,
        needs_attention: bool = False,
        read: bool = False,
    ) -> dict:
        self.calls.append(("insert", (conversation_id, role, content), {
            "conversation_name": conversation_name,
            "tool_calls": tool_calls,
            "needs_attention": needs_attention,
            "read": read,
        }))
        row = {
            "id": self._next_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "conversation_name": conversation_name,
            "tool_calls": tool_calls,
            "needs_attention": needs_attention,
            "read": read,
            "created_at": f"2026-01-01T00:00:{self._next_id:02d}Z",
        }
        self._next_id += 1
        self.rows.append(row)
        return row

    # -- reads ----------------------------------------------------------------
    def get_conversation(
        self, conversation_id: str, after_id: int | None = None
    ) -> list[dict]:
        self.calls.append(("get_conversation", (conversation_id, after_id), {}))
        # When a test pins an explicit conversation, return it; otherwise reflect
        # the rows actually inserted so the chat route's transcript (and thus the
        # task sent to the LLM) includes the just-stored visitor line.
        rows = self.conversation if self.conversation else self.rows
        if after_id is not None:
            rows = [r for r in rows if r["id"] > after_id]
        return rows

    def conversation_name_from_rows(self, rows: list[dict]) -> str | None:
        for row in rows:
            if row.get("conversation_name"):
                return row["conversation_name"]
        return None

    def list_conversations(self) -> list[dict]:
        self.calls.append(("list_conversations", (), {}))
        return self.inbox

    def open_conversation(self, conversation_id: str) -> list[dict]:
        self.calls.append(("open_conversation", (conversation_id,), {}))
        self.opened.append(conversation_id)
        return self.conversation

    def mark_resolved(self, conversation_id: str) -> None:
        self.calls.append(("mark_resolved", (conversation_id,), {}))
        self.resolved.append(conversation_id)

    # -- helpers --------------------------------------------------------------
    def call_names(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture
def fake_db(monkeypatch) -> FakeDB:
    """Install a FakeDB over ``app.db`` and return it for assertions."""
    fake = FakeDB()
    monkeypatch.setattr(db, "insert_message", fake.insert_message)
    monkeypatch.setattr(db, "get_conversation", fake.get_conversation)
    monkeypatch.setattr(
        db, "conversation_name_from_rows", fake.conversation_name_from_rows
    )
    monkeypatch.setattr(db, "list_conversations", fake.list_conversations)
    monkeypatch.setattr(db, "open_conversation", fake.open_conversation)
    monkeypatch.setattr(db, "mark_resolved", fake.mark_resolved)
    return fake


def make_fake_stream(
    *, tokens: list[str], tools: list[dict] | None = None, error: str | None = None
):
    """Build a fake ``agent.stream_reply`` async generator.

    Emits the given tool pieces first (if any), then the text tokens, then an
    optional error piece. Mirrors the shapes the real agent yields.
    """

    async def _stream(task: str, owner_name: str) -> AsyncIterator[dict[str, Any]]:
        for tool in tools or []:
            yield {
                "type": "tool",
                "phase": "calling",
                "name": tool.get("name", "faq_tool"),
                "detail": tool.get("detail"),
            }
            yield {
                "type": "tool",
                "phase": "done",
                "name": tool.get("name", "faq_tool"),
                "detail": None,
            }
        for tok in tokens:
            yield {"type": "token", "text": tok}
        if error is not None:
            yield {"type": "error", "message": error}

    return _stream


def parse_sse(text: str) -> list[dict]:
    """Parse an SSE body into a list of decoded JSON payloads."""
    payloads: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payloads.append(json.loads(line[len("data:"):].strip()))
    return payloads
