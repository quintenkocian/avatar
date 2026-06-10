"""Supabase data-access layer.

All ``messages`` table I/O lives here. Functions are synchronous; FastAPI runs
them in a threadpool (the route handlers are declared ``def``), so blocking
Supabase calls never stall the event loop.

The Supabase client is created lazily on first use so that simply importing this
module (e.g. in tests that only exercise other modules, or an AST/import check)
never requires credentials or a network connection.
"""

from __future__ import annotations

import logging
from typing import Any

from supabase import Client, create_client

from .config import settings

logger = logging.getLogger("avatar.db")

TABLE = "messages"

_client: Client | None = None


def get_client() -> Client:
    """Return the shared Supabase client, creating it on first use."""
    global _client
    if _client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_KEY are not configured; cannot reach the "
                "database. Set them in the project-root .env."
            )
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _client


def _table():
    return get_client().table(TABLE)


# --- Writes ------------------------------------------------------------------


def insert_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    conversation_name: str | None = None,
    tool_calls: Any | None = None,
    needs_attention: bool = False,
    read: bool = False,
) -> dict:
    """Insert one message row and return the inserted row dict."""
    payload: dict[str, Any] = {
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "needs_attention": needs_attention,
        "read": read,
    }
    if conversation_name is not None:
        payload["conversation_name"] = conversation_name
    if tool_calls is not None:
        payload["tool_calls"] = tool_calls

    result = _table().insert(payload).execute()
    return result.data[0]


# --- Reads -------------------------------------------------------------------


def get_conversation(
    conversation_id: str, after_id: int | None = None
) -> list[dict]:
    """Return rows for a conversation in chronological order.

    Ordered by ``created_at`` then ``id`` (stable tiebreak). When ``after_id`` is
    given, only rows with a strictly greater id are returned (used for polling
    newer human/avatar messages).
    """
    query = (
        _table()
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .order("id", desc=False)
    )
    if after_id is not None:
        query = query.gt("id", after_id)
    result = query.execute()
    return result.data or []


def get_conversation_name(conversation_id: str) -> str | None:
    """Derive the conversation name from its rows (helper, one query)."""
    return _name_from_rows(get_conversation(conversation_id))


def _name_from_rows(rows: list[dict]) -> str | None:
    """First non-empty ``conversation_name`` among the given rows, or None."""
    for row in rows:
        name = row.get("conversation_name")
        if name:
            return name
    return None


def conversation_name_from_rows(rows: list[dict]) -> str | None:
    """Public helper: derive a conversation name from already-fetched rows."""
    return _name_from_rows(rows)


def _initials(name: str | None) -> str:
    """Build up-to-two-letter initials from a name, falling back to '?'."""
    if not name:
        return "?"
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def list_conversations() -> list[dict]:
    """Return inbox summaries, most-recent first.

    One query of all rows (ordered newest-first), grouped in Python. Each summary
    matches the shape in ``docs/ARCHITECTURE.md`` section 3.
    """
    result = (
        _table()
        .select("*")
        .order("created_at", desc=True)
        .order("id", desc=True)
        .execute()
    )
    rows = result.data or []

    summaries: dict[str, dict] = {}
    order: list[str] = []

    for row in rows:
        cid = row["conversation_id"]
        if cid not in summaries:
            # rows are newest-first, so the first one seen is the latest message.
            order.append(cid)
            summaries[cid] = {
                "conversation_id": cid,
                "conversation_name": row.get("conversation_name"),
                "last_role": row.get("role", ""),
                "last_content": row.get("content", "") or "",
                "last_at": row.get("created_at", ""),
                "message_count": 0,
                "unread_count": 0,
                "needs_attention": False,
            }
        summary = summaries[cid]
        summary["message_count"] += 1
        # Capture a name if the latest row lacked one but an earlier row has it.
        if not summary["conversation_name"] and row.get("conversation_name"):
            summary["conversation_name"] = row.get("conversation_name")
        # Unread = visitor messages the owner has not seen.
        if row.get("role") == "visitor" and not row.get("read", False):
            summary["unread_count"] += 1
        if row.get("needs_attention", False):
            summary["needs_attention"] = True

    out: list[dict] = []
    for cid in order:
        summary = summaries[cid]
        summary["initials"] = _initials(summary.get("conversation_name"))
        out.append(summary)
    return out


# --- Open / resolve ----------------------------------------------------------


def open_conversation(conversation_id: str) -> list[dict]:
    """Open a thread for the owner: mark read + clear attention, return the thread.

    Implemented as a PostgREST ``update ... returning`` that flips ``read`` to true
    and ``needs_attention`` to false for any row currently unread or flagged, then
    one ``select`` of the full thread to return it in display order. This keeps it
    to two round-trips with no per-row chatter (the SPEC's intent). If nothing
    needed updating, the update is a cheap no-op match.
    """
    (
        _table()
        .update({"read": True, "needs_attention": False})
        .eq("conversation_id", conversation_id)
        .or_("read.eq.false,needs_attention.eq.true")
        .execute()
    )
    return get_conversation(conversation_id)


def mark_resolved(conversation_id: str) -> None:
    """Clear the needs-attention flag for a whole conversation."""
    (
        _table()
        .update({"needs_attention": False})
        .eq("conversation_id", conversation_id)
        .eq("needs_attention", True)
        .execute()
    )


def delete_conversation(conversation_id: str) -> None:
    """Delete all rows for a conversation (test cleanup helper)."""
    _table().delete().eq("conversation_id", conversation_id).execute()


__all__ = [
    "TABLE",
    "get_client",
    "insert_message",
    "get_conversation",
    "get_conversation_name",
    "conversation_name_from_rows",
    "list_conversations",
    "open_conversation",
    "mark_resolved",
    "delete_conversation",
]
