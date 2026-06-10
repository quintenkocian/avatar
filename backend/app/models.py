"""Pydantic request/response models for the HTTP API.

These mirror the JSON shapes pinned in ``docs/ARCHITECTURE.md`` section 8. The
backend reads/writes rows as plain dicts from Supabase; these models cover the
request bodies and the structured (non-streaming) responses.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --- Request bodies ----------------------------------------------------------


class ChatRequest(BaseModel):
    """Body for ``POST /api/chat`` and ``POST /api/instant``."""

    conversation_id: str
    name: str | None = None
    message: str


class LoginRequest(BaseModel):
    """Body for ``POST /admin/login``."""

    password: str


class AdminMessageRequest(BaseModel):
    """Body for ``POST /admin/conversations/{id}/message``."""

    content: str


# --- Response models ---------------------------------------------------------


class ConfigResponse(BaseModel):
    """``GET /api/config`` — no DB access."""

    owner_name: str


class MessageOut(BaseModel):
    """A single conversation row as returned to clients."""

    id: int
    role: str
    content: str
    created_at: str
    tool_calls: Any | None = None
    needs_attention: bool = False
    read: bool = False
    conversation_name: str | None = None


class ConversationResponse(BaseModel):
    """``GET /api/conversation`` and ``GET /admin/conversations/{id}``."""

    conversation_id: str
    conversation_name: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


class InstantResponse(BaseModel):
    """``POST /api/instant`` result."""

    found: bool
    question_number: int | None = None
    content: str | None = None
    avatar_id: int | None = None
    visitor_id: int | None = None


class ConversationSummary(BaseModel):
    """A row in the admin inbox list."""

    conversation_id: str
    conversation_name: str | None = None
    last_role: str
    last_content: str
    last_at: str
    message_count: int
    unread_count: int
    needs_attention: bool
    initials: str


class ConversationsListResponse(BaseModel):
    """``GET /admin/conversations``."""

    conversations: list[dict[str, Any]] = Field(default_factory=list)


class OkResponse(BaseModel):
    """Generic ``{"ok": bool}`` response."""

    ok: bool


__all__ = [
    "ChatRequest",
    "LoginRequest",
    "AdminMessageRequest",
    "ConfigResponse",
    "MessageOut",
    "ConversationResponse",
    "InstantResponse",
    "ConversationSummary",
    "ConversationsListResponse",
    "OkResponse",
]
