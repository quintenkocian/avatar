# Backend Test Plan

Comprehensive unit + integration tests for the Avatar FastAPI backend. The bulk
of the suite is **hermetic** (no network, no LLM, no live Supabase): the DB layer
and the agent stream are monkeypatched so route behaviour, auth, abuse guards and
prompt composition are tested deterministically. A small **`@pytest.mark.llm`**
tier exercises the real model (via `openai/gpt-5.4-nano`) and a real Supabase
round-trip, cleaning up every row it writes.

## How to run

```
cd backend
uv run pytest -q                      # hermetic suite (default; skips llm tier unless creds present)
uv run pytest -m llm -q               # live model + Supabase integration (writes & cleans up)
uv run pytest tests/test_supabase_connection.py -v   # standalone connectivity check
```

## Conventions

- Route handlers reference `db.*`, `agent.stream_reply`, `rate_limit.check` as
  module attributes, so tests `monkeypatch` those names on the modules.
- An autouse fixture resets the in-memory rate limiter before every test.
- The hermetic suite never constructs a Supabase client (the lazy client is never
  triggered because `db.*` is patched).

---

## 1. Config (`test_config.py`)
- [x] `settings` loads from `.env`: `OWNER_NAME`, `MODEL`, `SUPABASE_URL/KEY` non-empty.
- [x] `_get` treats empty string as unset and returns the default.
- [x] `MODEL` defaults to `openai/gpt-5.4-nano` when env unset.
- [x] `OWNER_NAME` defaults to `the owner` when env unset.
- [x] `SESSION_SECRET` derives from `avatar::<ADMIN_PASSWORD>` when unset.
- [x] `COOKIE_SECURE` is `True` only when env == `"1"`.
- [x] Abuse-guard constants: `MAX_MESSAGE_CHARS == 20000`, `RATE_LIMIT == "20/minute"`.
- [x] Cookie names: `ADMIN_COOKIE_NAME == "avatar_admin"`, conversation cookie set.
- [x] `PROJECT_ROOT` resolves to the repo root and `.env` exists there.

## 2. Knowledge / prompt composition (`test_knowledge.py`)
- [x] FAQs load from `faq.jsonl`; `FAQ_BY_NUMBER` keyed by `faq` int.
- [x] `find_faq(n)` returns a question+answer block for a known n; `None` for unknown.
- [x] `instant_answer_markdown(n)` restates the question (`**Qn:** ...`) then answer; `None` for unknown.
- [x] `build_system_prompt(owner)` interpolates the owner name (never hardcoded),
      explains the three-way visitor/avatar/human setup, lists FAQ routing numbers,
      and documents `faq_tool` + `push_tool`.
- [x] `build_user_task` labels visitor/avatar/human rows; human label includes owner name.
- [x] `build_user_task` appends a `pending_visitor` line when provided.
- [x] `_load_faqs` skips malformed JSONL lines without raising.

## 3. Security / admin auth (`test_security.py`)
- [x] `make_session_token` / `verify_session_token` round-trip; tampered token rejected.
- [x] `verify_session_token(None)` and `("")` are False.
- [x] Expired token (max_age=0) rejected.
- [x] `check_password` true for the configured password, false otherwise.
- [x] `check_password` fails closed when `ADMIN_PASSWORD` is empty.
- [x] `set_session_cookie` sets httpOnly cookie; `clear_session_cookie` deletes it.
- [x] `is_authenticated` / `require_admin` raise 401 without a valid cookie.

## 4. Rate limiter (`test_rate_limit.py`)
- [x] First 20 hits for a conversation pass; the 21st returns False.
- [x] Different `conversation_id`s have independent windows.
- [x] `reset()` clears state so the limit applies fresh.

## 5. Main helpers (`test_main_helpers.py`)
- [x] `_clamp_message` leaves short messages unchanged.
- [x] `_clamp_message` truncates to 20000 chars and appends the truncation note.
- [x] `_QN_RE` matches `Q1`, `q12`, case-insensitive; rejects `Q`, `Q123`, `hello`.
- [x] `_name_to_store` returns the provided name only when the thread has none yet.
- [x] `_sse` encodes a `data: <json>\n\n` frame.

## 6. Public API (`test_api_public.py`) — DB + agent mocked
- [x] `GET /api/config` returns `{owner_name}` from settings, no DB hit.
- [x] `GET /api/conversation` restores rows and derives the name from the rows.
- [x] `GET /api/conversation?after_id=` passes `after_id` through to the DB layer.
- [x] `POST /api/instant` with a known `Qn`: persists visitor + avatar rows, returns `found:true` + content.
- [x] `POST /api/instant` with unknown `Qn` / non-`Qn`: `found:false`, nothing persisted.
- [x] `POST /api/instant` rate-limited → 429, no DB writes.
- [x] `POST /api/chat` streams SSE: `start` → `token`* → `done` with a `message_id`.
- [x] `POST /api/chat` persists a visitor row then an avatar row (mocked agent text).
- [x] `POST /api/chat` surfaces tool pieces and stores `tool_calls`.
- [x] `POST /api/chat` rate-limited → 429 *before* any agent call (stream_reply not invoked).
- [x] `POST /api/chat` clamps an over-long visitor message before persisting/sending.
- [x] `GET /healthz` returns `ok` with no DB hit.

## 7. Admin API + auth gating (`test_api_admin.py`) — DB mocked
- [x] Every `/admin/*` data route returns **401 without a session cookie**:
      `me`, `conversations`, `conversations/{id}`, `message`, `resolve`.
- [x] `POST /admin/login` wrong password → 401, no cookie.
- [x] `POST /admin/login` correct password → 200 + `avatar_admin` httpOnly cookie.
- [x] With the cookie, `GET /admin/me` → 200.
- [x] `GET /admin/conversations` returns the inbox summaries from the DB layer.
- [x] `GET /admin/conversations/{id}` calls `open_conversation` (mark read + clear attention) and returns rows.
- [x] `POST /admin/conversations/{id}/message` inserts a `human` row (read, not needing attention).
- [x] `POST /admin/conversations/{id}/resolve` calls `mark_resolved`, returns ok.
- [x] `POST /admin/logout` clears the cookie.

## 8. Static serving (`test_static.py`)
- [x] `GET /` serves the built `index.html` (or placeholder when unbuilt).
- [x] `GET /admin` serves the built `admin.html`.
- [x] `GET /{name}.png` rejects path traversal (`..`), 404 for a missing asset.
- [x] `GET /favicon.ico` returns a file or 204.

## 9. Live integration (`test_integration_llm.py`) — `@pytest.mark.llm`
- [x] Real `agent.stream_reply` against `gpt-5.4-nano` yields token pieces for a simple prompt.
- [x] Full `POST /api/chat` against real Supabase persists visitor + avatar rows, then the test deletes the conversation.
- [x] `faq_tool` / `push_tool` are wired (push is a no-op safe path when creds absent).

---

## Results

- [x] Hermetic suite green (`uv run pytest -q -m "not llm"`).
- [x] Live integration green (`uv run pytest -m llm -q`).
- [x] All test conversations deleted from Supabase after the run.
