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
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import Client, create_client

from .config import settings

logger = logging.getLogger("avatar.db")

TABLE = "messages"
ARCHIVE_TABLE = "archive"
SETTINGS_TABLE = "settings"
FAQ_TABLE = "faq"

# The settings table holds a single pinned row (see the README MORE section).
SETTINGS_ROW_ID = 1

# Columns copied verbatim when a whole conversation moves between ``messages``
# and ``archive``. ``id`` is intentionally omitted so the destination table
# assigns its own identity; ``created_at`` is preserved so ordering/timestamps
# survive the round-trip.
_PORTABLE_COLUMNS = (
    "conversation_id",
    "conversation_name",
    "role",
    "content",
    "tool_calls",
    "needs_attention",
    "read",
    "created_at",
)

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


def _table(name: str = TABLE):
    return get_client().table(name)


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
    conversation_id: str, after_id: int | None = None, *, table: str = TABLE
) -> list[dict]:
    """Return rows for a conversation in chronological order.

    Ordered by ``created_at`` then ``id`` (stable tiebreak). When ``after_id`` is
    given, only rows with a strictly greater id are returned (used for polling
    newer human/avatar messages). ``table`` selects the live ``messages`` table
    (default) or the ``archive`` table for viewing an archived thread.
    """
    query = (
        _table(table)
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


def list_conversations(*, table: str = TABLE) -> list[dict]:
    """Return inbox summaries, most-recent first.

    One query of all rows (ordered newest-first), grouped in Python. Each summary
    matches the shape in ``docs/ARCHITECTURE.md`` section 3. ``table`` selects the
    live ``messages`` table (default) or the ``archive`` table.
    """
    result = (
        _table(table)
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
    """Open a thread for the owner: mark read, return the thread.

    Implemented as a PostgREST ``update`` that flips ``read`` to true for any
    currently-unread row, then one ``select`` of the full thread to return it in
    display order. This keeps it to two round-trips with no per-row chatter (the
    SPEC's intent). If nothing needed updating, the update is a cheap no-op match.

    Opening does NOT touch ``needs_attention``: the attention flag persists until
    the owner explicitly clicks "Mark resolved" (see ``mark_resolved``).
    """
    (
        _table()
        .update({"read": True})
        .eq("conversation_id", conversation_id)
        .eq("read", False)
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


def delete_conversation(conversation_id: str, *, table: str = TABLE) -> None:
    """Delete all rows for a conversation (test cleanup helper)."""
    _table(table).delete().eq("conversation_id", conversation_id).execute()


# --- Archive / restore -------------------------------------------------------


def _portable_rows(rows: list[dict]) -> list[dict]:
    """Project rows onto the columns safe to copy across tables."""
    out: list[dict] = []
    for row in rows:
        out.append({k: row.get(k) for k in _PORTABLE_COLUMNS if k in row})
    return out


def _move_conversation(conversation_id: str, src: str, dst: str) -> int:
    """Copy a whole conversation from ``src`` to ``dst`` then delete it from ``src``.

    Returns the number of rows moved. The copy happens first; the source is only
    deleted once the insert succeeds, so a failure can never lose data (at worst
    it leaves a duplicate in ``dst``, which is far safer than a dropped thread).
    """
    rows = get_conversation(conversation_id, table=src)
    if not rows:
        return 0
    payload = _portable_rows(rows)
    _table(dst).insert(payload).execute()
    _table(src).delete().eq("conversation_id", conversation_id).execute()
    return len(rows)


def archive_conversation(conversation_id: str) -> int:
    """Move a whole conversation from ``messages`` into ``archive``."""
    return _move_conversation(conversation_id, TABLE, ARCHIVE_TABLE)


def restore_conversation(conversation_id: str) -> int:
    """Move a whole conversation from ``archive`` back into ``messages``."""
    return _move_conversation(conversation_id, ARCHIVE_TABLE, TABLE)


def list_archived_conversations() -> list[dict]:
    """Inbox-style summaries for the archive table, most-recent first."""
    return list_conversations(table=ARCHIVE_TABLE)


def get_archived_conversation(conversation_id: str) -> list[dict]:
    """Return the full archived thread in display order."""
    return get_conversation(conversation_id, table=ARCHIVE_TABLE)


def _latest_at_by_conversation(rows: list[dict]) -> dict[str, str]:
    """Map each conversation_id to its most recent ``created_at`` string."""
    latest: dict[str, str] = {}
    for row in rows:
        cid = row.get("conversation_id")
        ts = row.get("created_at") or ""
        if cid is None:
            continue
        if cid not in latest or ts > latest[cid]:
            latest[cid] = ts
    return latest


def _parse_ts(value: str) -> datetime | None:
    """Parse a Postgres timestamptz string into an aware UTC datetime."""
    if not value:
        return None
    text = value.strip()
    # Normalise common forms: trailing Z, and space-separated date/time.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text.replace(" ", "T"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def archive_inactive(hours: int = 72, *, now: datetime | None = None) -> list[str]:
    """Archive every conversation with no activity in the last ``hours``.

    A conversation is inactive when its newest message is older than the cutoff.
    Returns the list of conversation_ids that were archived (whole-conversation
    semantics, like the per-thread archive button).
    """
    reference = now or datetime.now(timezone.utc)
    cutoff = reference - timedelta(hours=hours)

    rows = _table(TABLE).select("conversation_id,created_at").execute().data or []
    latest = _latest_at_by_conversation(rows)

    stale: list[str] = []
    for cid, ts in latest.items():
        parsed = _parse_ts(ts)
        if parsed is not None and parsed < cutoff:
            stale.append(cid)

    archived: list[str] = []
    for cid in stale:
        try:
            if archive_conversation(cid) > 0:
                archived.append(cid)
        except Exception:  # pragma: no cover - defensive; keep going on one failure
            logger.exception("Failed to archive inactive conversation %s", cid)
    return archived


# --- Counts / export ---------------------------------------------------------


def count_conversations(*, table: str = TABLE) -> int:
    """Number of distinct conversations in ``table``."""
    rows = _table(table).select("conversation_id").execute().data or []
    return len({r.get("conversation_id") for r in rows})


def export_rows(*, table: str = TABLE) -> list[dict]:
    """All rows in ``table`` in chronological order (for the jsonl download)."""
    result = (
        _table(table)
        .select("*")
        .order("created_at", desc=False)
        .order("id", desc=False)
        .execute()
    )
    return result.data or []


# --- Settings (additional instructions) --------------------------------------


def get_additional_instructions() -> str:
    """Return the admin's additional-instructions markdown (empty if unset)."""
    try:
        result = (
            _table(SETTINGS_TABLE)
            .select("additional_instructions")
            .eq("id", SETTINGS_ROW_ID)
            .limit(1)
            .execute()
        )
    except Exception:  # pragma: no cover - defensive; never break a chat turn
        logger.exception("Failed to read settings; using empty instructions")
        return ""
    rows = result.data or []
    if not rows:
        return ""
    return rows[0].get("additional_instructions") or ""


def set_additional_instructions(text: str) -> str:
    """Upsert the single settings row with new instructions; return the stored text."""
    payload = {"id": SETTINGS_ROW_ID, "additional_instructions": text}
    result = _table(SETTINGS_TABLE).upsert(payload).execute()
    rows = result.data or []
    if rows:
        return rows[0].get("additional_instructions") or ""
    return text


# --- FAQ ---------------------------------------------------------------------


def _normalise_faq(row: dict) -> dict:
    """Coerce a raw faq row to the canonical {id, concise, question, answer}."""
    return {
        "id": int(row.get("id")),
        "concise": str(row.get("concise") or ""),
        "question": str(row.get("question") or ""),
        "answer": str(row.get("answer") or ""),
    }


def list_faqs() -> list[dict]:
    """Return all FAQ rows ordered by id (the FAQ number)."""
    result = _table(FAQ_TABLE).select("*").order("id", desc=False).execute()
    return [_normalise_faq(r) for r in (result.data or [])]


def get_faq(faq_id: int) -> dict | None:
    """Return a single FAQ row by id, or None."""
    result = (
        _table(FAQ_TABLE).select("*").eq("id", faq_id).limit(1).execute()
    )
    rows = result.data or []
    return _normalise_faq(rows[0]) if rows else None


def _next_faq_id() -> int:
    """The next FAQ id: max(existing id) + 1 (1 when the table is empty)."""
    result = (
        _table(FAQ_TABLE).select("id").order("id", desc=True).limit(1).execute()
    )
    rows = result.data or []
    return (int(rows[0]["id"]) + 1) if rows else 1


def create_faq(concise: str, question: str, answer: str) -> dict:
    """Insert a new FAQ row with id = max(id)+1; return the stored row."""
    payload = {
        "id": _next_faq_id(),
        "concise": concise,
        "question": question,
        "answer": answer,
    }
    result = _table(FAQ_TABLE).insert(payload).execute()
    return _normalise_faq(result.data[0])


def update_faq(
    faq_id: int, concise: str, question: str, answer: str
) -> dict | None:
    """Update an existing FAQ row; return the stored row, or None if absent."""
    payload = {"concise": concise, "question": question, "answer": answer}
    result = (
        _table(FAQ_TABLE).update(payload).eq("id", faq_id).execute()
    )
    rows = result.data or []
    return _normalise_faq(rows[0]) if rows else None


def delete_faq(faq_id: int) -> None:
    """Delete a FAQ row by id."""
    _table(FAQ_TABLE).delete().eq("id", faq_id).execute()


def upsert_faq(faq_id: int, concise: str, question: str, answer: str) -> dict:
    """Insert-or-update a FAQ row by id (used by the seeding script)."""
    payload = {
        "id": faq_id,
        "concise": concise,
        "question": question,
        "answer": answer,
    }
    result = _table(FAQ_TABLE).upsert(payload).execute()
    return _normalise_faq(result.data[0])


__all__ = [
    "TABLE",
    "ARCHIVE_TABLE",
    "SETTINGS_TABLE",
    "FAQ_TABLE",
    "get_client",
    "insert_message",
    "get_conversation",
    "get_conversation_name",
    "conversation_name_from_rows",
    "list_conversations",
    "open_conversation",
    "mark_resolved",
    "delete_conversation",
    "archive_conversation",
    "restore_conversation",
    "list_archived_conversations",
    "get_archived_conversation",
    "archive_inactive",
    "count_conversations",
    "export_rows",
    "get_additional_instructions",
    "set_additional_instructions",
    "list_faqs",
    "get_faq",
    "create_faq",
    "update_faq",
    "delete_faq",
    "upsert_faq",
]
