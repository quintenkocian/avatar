"""FastAPI application: HTTP API + static frontend serving.

Implements the contract in ``docs/ARCHITECTURE.md`` section 8. Public routes
power the visitor chat (config, conversation restore/poll, instant Qn answers,
and the streaming chat). Admin routes power the owner dashboard and are guarded
by a signed session cookie. The built frontend (if present) is served from
``STATIC_DIR``; the app still starts cleanly when the frontend has not been
built yet.

Blocking Supabase I/O is wrapped with ``run_in_threadpool`` so the async event
loop is never stalled.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import agent, db, knowledge, rate_limit, security
from .config import settings
from .models import (
    AdminMessageRequest,
    ChatRequest,
    LoginRequest,
)

logger = logging.getLogger("avatar")

app = FastAPI(title="Avatar", version="0.1.0")

# A bare "Qn" message (case-insensitive), 1–2 digits, is the instant shortcut.
_QN_RE = re.compile(r"^q(\d{1,2})$", re.IGNORECASE)


# --- Helpers -----------------------------------------------------------------


def _clamp_message(message: str) -> str:
    """Clamp a visitor message to MAX_MESSAGE_CHARS, appending the note if cut.

    The clamped text is what gets stored AND sent to the LLM (per SPEC #12).
    """
    if len(message) > settings.MAX_MESSAGE_CHARS:
        return message[: settings.MAX_MESSAGE_CHARS] + settings.TRUNCATION_NOTE
    return message


def _existing_name(rows: list[dict]) -> str | None:
    """Return the conversation name already stored in the given rows."""
    return db.conversation_name_from_rows(rows)


def _name_to_store(provided: str | None, rows: list[dict]) -> str | None:
    """Decide whether to attach a name to a new row.

    Only set it when the visitor provided one AND the conversation has none yet,
    so the first non-empty name sticks for the whole thread.
    """
    provided = (provided or "").strip()
    if not provided:
        return None
    if _existing_name(rows):
        return None
    return provided


def _sse(payload: dict[str, Any]) -> str:
    """Encode a payload as a single SSE ``data:`` frame."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# --- Public API --------------------------------------------------------------


@app.get("/api/config")
def get_config() -> JSONResponse:
    """Owner name only — no DB hit. Doubles as the Fly health check path."""
    return JSONResponse({"owner_name": settings.OWNER_NAME})


@app.get("/api/conversation")
async def api_conversation(
    conversation_id: str, after_id: int | None = None
) -> JSONResponse:
    """Restore a conversation (no ``after_id``) or poll for newer rows."""
    rows = await run_in_threadpool(
        db.get_conversation, conversation_id, after_id
    )
    # Derive the name from a name-bearing row if present. On a poll (after_id set)
    # the delta may not contain one, in which case the client keeps its cached
    # value; on a full restore the first visitor row carries it.
    name = _existing_name(rows)
    return JSONResponse(
        {
            "conversation_id": conversation_id,
            "conversation_name": name,
            "messages": rows,
        }
    )


@app.post("/api/instant")
async def api_instant(body: ChatRequest) -> JSONResponse:
    """Instant ``Qn`` answer with no LLM call.

    Detects a bare ``Qn``; if the FAQ exists, persists a visitor row and an avatar
    row and returns the avatar markdown. Otherwise returns ``found: false`` and
    persists nothing (the frontend falls back to ``/api/chat``).
    """
    if not await run_in_threadpool(rate_limit.check, body.conversation_id):
        return JSONResponse({"error": "rate_limited"}, status_code=429)

    raw = (body.message or "").strip()
    match = _QN_RE.match(raw)
    if not match:
        return JSONResponse({"found": False})

    n = int(match.group(1))
    answer = knowledge.instant_answer_markdown(n)
    if answer is None:
        return JSONResponse({"found": False})

    # Clamp defensively (a bare Qn is tiny, but keep the single code path honest).
    visitor_content = _clamp_message(body.message)

    existing = await run_in_threadpool(db.get_conversation, body.conversation_id)
    name = _name_to_store(body.name, existing)

    visitor_row = await run_in_threadpool(
        db.insert_message,
        body.conversation_id,
        "visitor",
        visitor_content,
        conversation_name=name,
    )
    avatar_row = await run_in_threadpool(
        db.insert_message,
        body.conversation_id,
        "avatar",
        answer,
        tool_calls={"instant": n},
        read=True,
    )
    return JSONResponse(
        {
            "found": True,
            "question_number": n,
            "content": answer,
            "avatar_id": avatar_row["id"],
            "visitor_id": visitor_row["id"],
        }
    )


@app.post("/api/chat")
async def api_chat(body: ChatRequest) -> Response:
    """Stream the avatar's reply via SSE.

    Order of operations (per the contract): rate-limit (429 before any model
    call), clamp, persist the visitor row, build the single-user-task transcript,
    stream the agent reply, then persist the avatar row before emitting ``done``.
    """
    if not await run_in_threadpool(rate_limit.check, body.conversation_id):
        return JSONResponse({"error": "rate_limited"}, status_code=429)

    clamped = _clamp_message(body.message or "")

    # Persist the visitor row first; set the name if the thread has none yet.
    existing = await run_in_threadpool(db.get_conversation, body.conversation_id)
    name = _name_to_store(body.name, existing)
    await run_in_threadpool(
        db.insert_message,
        body.conversation_id,
        "visitor",
        clamped,
        conversation_name=name,
    )

    # Full conversation INCLUDING the just-stored visitor line becomes the task.
    transcript = await run_in_threadpool(
        db.get_conversation, body.conversation_id
    )
    task = knowledge.build_user_task(transcript, settings.OWNER_NAME)

    async def event_stream() -> AsyncIterator[str]:
        yield _sse({"type": "start"})
        full_text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        errored = False

        try:
            async for piece in agent.stream_reply(task, settings.OWNER_NAME):
                ptype = piece.get("type")
                if ptype == "token":
                    full_text_parts.append(piece.get("text", ""))
                    yield _sse(piece)
                elif ptype == "tool":
                    if piece.get("phase") == "calling":
                        tool_calls.append(
                            {
                                "name": piece.get("name"),
                                "detail": piece.get("detail"),
                            }
                        )
                    yield _sse(piece)
                elif ptype == "error":
                    errored = True
                    yield _sse(piece)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Chat stream failed")
            errored = True
            yield _sse({"type": "error", "message": str(exc)})

        full_text = "".join(full_text_parts).strip()

        # Persist whatever was generated (even on disconnect/partial), so the
        # owner sees the avatar's contribution. Skip only if nothing at all came
        # back and we already reported an error.
        if full_text or not errored:
            # Flag the owner if the Avatar pinged them via the push tool.
            needs_attention = any(
                tc.get("name") == agent.push_tool.name for tc in tool_calls
            )
            try:
                avatar_row = await run_in_threadpool(
                    db.insert_message,
                    body.conversation_id,
                    "avatar",
                    full_text,
                    tool_calls=(tool_calls or None),
                    read=True,
                    needs_attention=needs_attention,
                )
                yield _sse(
                    {"type": "done", "message_id": avatar_row["id"]}
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Failed to persist avatar row")
                yield _sse({"type": "error", "message": str(exc)})
        else:
            yield _sse({"type": "done", "message_id": None})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# --- Admin API ---------------------------------------------------------------


@app.post("/admin/login")
async def admin_login(body: LoginRequest) -> JSONResponse:
    """Authenticate the owner; set the session cookie on success."""
    if not security.check_password(body.password):
        return JSONResponse({"ok": False}, status_code=401)
    response = JSONResponse({"ok": True})
    security.set_session_cookie(response)
    return response


@app.post("/admin/logout")
async def admin_logout() -> JSONResponse:
    """Clear the admin session cookie."""
    response = JSONResponse({"ok": True})
    security.clear_session_cookie(response)
    return response


@app.get("/admin/me")
async def admin_me(_: None = Depends(security.require_admin)) -> JSONResponse:
    """Return ``{"ok": true}`` if the caller is authenticated, else 401."""
    return JSONResponse({"ok": True})


@app.get("/admin/conversations")
async def admin_list_conversations(
    _: None = Depends(security.require_admin),
) -> JSONResponse:
    """Inbox summaries, most-recent first."""
    conversations = await run_in_threadpool(db.list_conversations)
    return JSONResponse({"conversations": conversations})


@app.get("/admin/conversations/{conversation_id}")
async def admin_open_conversation(
    conversation_id: str, _: None = Depends(security.require_admin)
) -> JSONResponse:
    """Open a thread: mark read + clear attention, return the full thread."""
    rows = await run_in_threadpool(db.open_conversation, conversation_id)
    return JSONResponse(
        {
            "conversation_id": conversation_id,
            "conversation_name": _existing_name(rows),
            "messages": rows,
        }
    )


@app.post("/admin/conversations/{conversation_id}/message")
async def admin_post_message(
    conversation_id: str,
    body: AdminMessageRequest,
    _: None = Depends(security.require_admin),
) -> JSONResponse:
    """Insert a human (owner) message. The Avatar does NOT react to it."""
    row = await run_in_threadpool(
        db.insert_message,
        conversation_id,
        "human",
        body.content,
        read=True,
        needs_attention=False,
    )
    return JSONResponse({"message": row})


@app.post("/admin/conversations/{conversation_id}/resolve")
async def admin_resolve(
    conversation_id: str, _: None = Depends(security.require_admin)
) -> JSONResponse:
    """Clear the needs-attention flag for the conversation."""
    await run_in_threadpool(db.mark_resolved, conversation_id)
    return JSONResponse({"ok": True})


# --- Static frontend serving -------------------------------------------------

_PLACEHOLDER = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<title>Avatar</title></head><body style='font-family:sans-serif;"
    "max-width:40rem;margin:4rem auto;padding:0 1rem;line-height:1.5'>"
    "<h1>Avatar backend is running</h1>"
    "<p>The frontend has not been built yet. Build it with "
    "<code>npm run build</code> in <code>frontend/</code> (output goes to "
    "<code>frontend/dist</code>), or set <code>STATIC_DIR</code> to the built "
    "assets. The API is live at <code>/api/config</code>.</p>"
    "</body></html>"
)


def _static_file(name: str) -> Path | None:
    """Return the path to a built static file if it exists, else None."""
    candidate = settings.STATIC_DIR / name
    if candidate.is_file():
        return candidate
    return None


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> Response:
    """Serve the visitor page (or a friendly placeholder if not built)."""
    path = _static_file("index.html")
    if path is not None:
        return FileResponse(path)
    return HTMLResponse(_PLACEHOLDER)


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin() -> Response:
    """Serve the admin page (NOT guarded; the gate is client-side + API auth)."""
    path = _static_file("admin.html")
    if path is not None:
        return FileResponse(path)
    return HTMLResponse(_PLACEHOLDER)


@app.get("/icons.svg")
async def serve_icons() -> Response:
    """Serve the icon sprite if present."""
    path = _static_file("icons.svg")
    if path is not None:
        return FileResponse(path, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="not found")


@app.get("/favicon.ico")
async def serve_favicon() -> Response:
    """Serve a favicon if present, else 204 (no content) to avoid noisy 404s."""
    for name in ("favicon.ico", "favicon.png", "favicon.svg"):
        path = _static_file(name)
        if path is not None:
            return FileResponse(path)
    return Response(status_code=204)


@app.get("/{filename}.png")
async def serve_png(filename: str) -> Response:
    """Serve top-level PNG assets (avatar images) from the static dir."""
    # Reject any path traversal; only a bare filename is allowed.
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=404, detail="not found")
    path = _static_file(f"{filename}.png")
    if path is not None:
        return FileResponse(path, media_type="image/png")
    raise HTTPException(status_code=404, detail="not found")


def _mount_assets() -> None:
    """Mount the built ``/assets`` directory if it exists.

    Done at import time but guarded so a missing directory never crashes startup.
    """
    assets_dir = settings.STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=str(assets_dir)), name="assets"
        )
    else:
        logger.info(
            "Static assets directory %s not found; skipping /assets mount "
            "(frontend not built yet).",
            assets_dir,
        )


_mount_assets()


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> PlainTextResponse:
    """Liveness probe that never touches the DB."""
    return PlainTextResponse("ok")
