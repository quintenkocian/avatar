# Avatar — Build Architecture & Interface Contract

This is the shared, authoritative contract for the implementation. It pins down the
file layout, the exact HTTP API shapes, the SSE wire format, the agent prompt, and the
frontend wiring so that independently-built modules fit together with no drift.

**Authority:** `SPEC.md` wins on behaviour/backend; `design-system/` wins on look/feel.
Where they conflict, this doc records the resolution (see "Resolved conflicts").

Owner for this build: **Quinten Kocian** (from `OWNER_NAME` env — never hardcode it).
Model for dev/test: `openai/gpt-5.4-nano` (already in `.env`).

---

## 1. Repository layout (target)

```
backend/
  app/
    __init__.py
    config.py          # env settings (pydantic Settings or plain), paths, constants
    models.py          # pydantic request/response models + Message dataclass
    knowledge.py       # load knowledge.md/style.md/faq.jsonl; build system prompt; faq lookup
    db.py              # Supabase data-access layer (all table I/O)
    security.py        # admin session cookie sign/verify (itsdangerous), auth dependency
    rate_limit.py      # limits moving-window per conversation_id
    agent.py           # OpenAI Agents SDK + OpenRouter client, tools, streaming runner
    main.py            # FastAPI app: routes + static serving
  tests/
    test_supabase_connection.py   # EXISTS — do not break
    test_knowledge.py
    test_security.py
    test_rate_limit.py
    test_api_public.py            # chat/instant/conversation (nano model OK)
    test_api_admin.py             # auth gating, login, thread open, post, resolve
    conftest.py                   # shared fixtures (TestClient, cleanup of test rows)
  pyproject.toml       # EXISTS
frontend/
  package.json
  tsconfig.json
  vite.config.ts
  index.html           # visitor page (served at /)
  admin.html           # admin page (served at /admin)
  public/
    icons.svg                 # copied from design-system/icons.svg
    avatar-human.png          # copied from design-system/assets/
    avatar-robot.png
    avatar-robot-round.png
    favicon (optional)
  src/
    styles/
      tokens.css       # copied from design-system/tokens.css (verbatim)
      components.css    # copied from design-system/components.css (verbatim)
      visitor.css       # page-specific
      admin.css         # page-specific
    api.ts             # typed fetch client for the whole backend API (SHARED CONTRACT)
    theme.ts           # dark/light toggle, persisted in localStorage['avatar-theme']
    util.ts            # initials(), escaping, markdown render, time formatting, uuid
    markdown.ts        # tiny safe markdown -> HTML (or use a small dep)
    visitor/main.ts    # visitor screen logic (entry for index.html)
    admin/main.ts      # admin screen logic (entry for admin.html)
Dockerfile             # multi-stage: node build frontend -> python run backend
.dockerignore
scripts/
  start_pc.ps1  stop_pc.ps1  start_mac.sh  stop_mac.sh
  deploy.sh  fly.toml  wordpress-embed.html
test/
  backend-test-plan.md       # checkbox plan
  frontend-test-plan.md
  e2e-test-plan.md
docs/ARCHITECTURE.md   # this file
```

`reference/` is inspiration only — do NOT import from it. `pypdf` is NOT a dependency.

---

## 2. Config (`config.py`)

Load `.env` from the **project root** (`Path(__file__).resolve().parents[2] / ".env"`),
`override=True`. Expose a singleton `settings`:

- `OPENROUTER_API_KEY: str`
- `MODEL: str` (default `"openai/gpt-5.4-nano"`)
- `OWNER_NAME: str` (default `"the owner"` — but it is set)
- `ADMIN_PASSWORD: str`
- `PUSHOVER_USER`, `PUSHOVER_TOKEN` (optional; push is a no-op-with-log if missing)
- `SUPABASE_URL`, `SUPABASE_KEY`
- `SESSION_SECRET: str` — default `f"avatar::{ADMIN_PASSWORD}"` if unset
- `COOKIE_SECURE: bool` — from `COOKIE_SECURE` == "1"
- `KNOWLEDGE_DIR: Path` — env `KNOWLEDGE_DIR` or default project_root/`knowledge`
- `STATIC_DIR: Path` — env `STATIC_DIR` or default project_root/`frontend/dist`
- `OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"`
- Constants: `MAX_MESSAGE_CHARS = 20000`, `TRUNCATION_NOTE = "\n\n[...message truncated as it's too long; ask the visitor to send something more concise]"`, `RATE_LIMIT = "20/minute"`.

`OPENROUTER_BASE_URL` etc. must come from config, not be scattered.

---

## 3. Data layer (`db.py`)

One module-level Supabase `Client` (`create_client(SUPABASE_URL, SUPABASE_KEY)`).
Table: `messages`. Columns: `id` (bigint identity), `conversation_id` (uuid str),
`conversation_name` (text|null), `role` ('visitor'|'avatar'|'human'), `content` (text),
`tool_calls` (jsonb|null), `needs_attention` (bool), `read` (bool), `created_at` (timestamptz).

Functions (all synchronous; FastAPI runs them in a threadpool via `def` endpoints OR wrap
with `run_in_threadpool`):

- `insert_message(conversation_id, role, content, *, conversation_name=None, tool_calls=None, needs_attention=False, read=False) -> dict` — returns inserted row.
- `get_conversation(conversation_id, after_id: int | None = None) -> list[dict]` — rows for a
  conversation ordered `created_at asc` (tiebreak `id asc`); if `after_id`, only `id > after_id`.
- `get_conversation_name(conversation_id) -> str | None` — derive from rows already fetched
  where possible; helper only.
- `list_conversations() -> list[dict]` — one query of all rows ordered `created_at desc`, grouped
  in Python into summaries (most-recent first). Each summary:
  `{conversation_id, conversation_name, last_role, last_content, last_at, message_count,
    unread_count, needs_attention, initials}` where `unread_count` counts rows with
  `read=false AND role='visitor'` (visitor messages the owner hasn't seen), `needs_attention` is
  OR across rows. `initials` derived from conversation_name or "?".
- `open_conversation(conversation_id) -> list[dict]` — **single round-trip**: PostgREST
  `update(...).eq("conversation_id", id).eq("read", false).execute()` setting `read=true`
  for currently-unread rows, then return the FULL conversation (one extra select). Net: opening
  marks read and yields the thread; it does NOT touch `needs_attention` — the attention flag
  persists until the owner clicks "Mark resolved" (`mark_resolved`). Keep it to as few calls as
  the client allows; the SPEC's intent is "no per-row chatter".
- `mark_resolved(conversation_id) -> None` — set `needs_attention=false` for the conversation.
  This is the ONLY path that clears attention.
- `delete_conversation(conversation_id) -> None` — test cleanup helper.

Use the supabase-py v2 sync client. Handle the deprecation warnings already seen (harmless).

---

## 4. Knowledge & prompt (`knowledge.py`)

- Load on import (cache in module): `knowledge.md`, `style.md`, `faq.jsonl` from `KNOWLEDGE_DIR`.
- `FAQS: list[dict]` each `{faq:int, question:str, answer:str, query:str}`.
- `FAQ_BY_NUMBER: dict[int, dict]`.
- `find_faq(n: int) -> str | None` — returns formatted `"### Question {n}\n{question}\n\n### Answer\n{answer}"` or None.
- `instant_answer_markdown(n: int) -> str | None` — the **visitor-facing** instant reply body:
  `f"**Q{n}:** {question}\n\n{answer}"` (restates the question before the answer, per SPEC). None if missing.
- `build_system_prompt(owner_name: str) -> str` — composes:
  1. Role: you are the **digital twin** of `{owner_name}`, on their website, talking to visitors.
     Explain the THREE-WAY setup: the real human `{owner_name}` may also join and post; their
     messages are labelled and already in the transcript; do not impersonate them, build on what
     they said. If asked, say you are an AI digital twin of `{owner_name}`.
  2. The full `knowledge.md`.
  3. The full `style.md`.
  4. FAQ routing block: "Your faq_tool returns canonical answers by number. If the visitor's
     question matches one of these, call faq_tool with that number and relay the answer verbatim
     in markdown (keep links as markdown)." then list each FAQ as `\n{faq}. {query}` (the short
     routing phrasings).
  5. Tool rules: faq_tool(question_number:int); push_tool(message:str) — use push_tool when the
     visitor wants to get in touch (first ask for their email, then push it), or when you cannot
     answer (push the question, and tell the visitor you've notified `{owner_name}`). Never invent
     answers. Make tool calls in parallel where useful.
- `build_user_task(messages: list[dict], owner_name: str, pending_visitor: str) -> str` —
  renders the whole conversation as ONE user task. Label roles: `Visitor`, `Avatar (you)`,
  `{owner_name} (the human)`. End with the latest visitor message to respond to. Format like:
  ```
  Here is the full conversation so far. Respond as the Avatar to the latest Visitor message.

  Visitor: ...
  Avatar (you): ...
  {owner} (the human): ...
  Visitor: <pending_visitor>
  ```
  (The transcript already includes the just-stored pending visitor line, so pass either the stored
  list including it, or the list + pending separately — pick one and be consistent.)

---

## 5. Agent (`agent.py`) — OpenAI Agents SDK via OpenRouter

Idiomatic current usage (verify against the installed `openai-agents` package before finalizing —
you MAY run `uv run python -c "import agents, inspect; ..."` to confirm names):

```python
from openai import AsyncOpenAI
from agents import Agent, Runner, OpenAIChatCompletionsModel, function_tool, set_tracing_disabled
from openai.types.responses import ResponseTextDeltaEvent

set_tracing_disabled(True)  # no OpenAI key; OpenRouter only
_client = AsyncOpenAI(base_url=settings.OPENROUTER_BASE_URL, api_key=settings.OPENROUTER_API_KEY)
_model = OpenAIChatCompletionsModel(model=settings.MODEL, openai_client=_client)
```

- `faq_tool(question_number: int) -> str` — wraps `knowledge.find_faq`.
- `push_tool(message: str) -> str` — Pushover POST (from `reference/push.py`); if creds missing,
  log and return a benign string (don't crash). Records nothing in DB itself.
- `build_agent(owner_name) -> Agent` with `instructions=build_system_prompt(owner_name)`,
  `model=_model`, `tools=[faq_tool, push_tool]`.
- `async def stream_reply(task: str, owner_name: str) -> AsyncIterator[StreamPiece]` — uses
  `Runner.run_streamed(agent, task)` and yields normalized pieces:
  - `{"type":"token","text": delta}` for `raw_response_event` + `ResponseTextDeltaEvent`
  - `{"type":"tool","phase":"calling","name": tool_name,"detail": optional}` on `tool_called`
  - `{"type":"tool","phase":"done","name": tool_name,"detail": optional}` on `tool_output`
  - The caller accumulates the full text and the list of tool_calls for persistence.
  Expose enough to get `final text` and `tool_calls` summary at the end.

Tool-status detail mapping for the UI (e.g. `faq_tool · curriculum`): include the tool name; a
short detail (like the matched query) is nice-to-have, not required.

---

## 6. Security (`security.py`)

- `itsdangerous.TimestampSigner` (or URLSafeTimedSerializer) keyed by `SESSION_SECRET`.
- `make_session_token() -> str` and `verify_session_token(token) -> bool` (max_age e.g. 7 days).
- Cookie name `avatar_admin`, `httponly=True`, `samesite="lax"`, `secure=settings.COOKIE_SECURE`,
  `path="/"`.
- FastAPI dependency `require_admin(request)` → 401 if cookie missing/invalid. Guards every
  `/admin/*` data route (NOT `/admin` static page, NOT `/admin/login`).

---

## 7. Rate limit (`rate_limit.py`)

- `limits` moving-window, in-memory storage, `20/minute` per `conversation_id`.
- `check(conversation_id) -> bool` (True = allowed). Used in chat + instant BEFORE any model call.
  On False the route returns HTTP 429 `{"error":"rate_limited"}`.

---

## 8. HTTP API (`main.py`)

All JSON unless noted. `conversation_id` is a client-minted UUID string.

### Public
- `GET /api/config` → `{"owner_name": settings.OWNER_NAME}` — no DB. (Fly health check path.)
- `GET /api/conversation?conversation_id=<uuid>&after_id=<int?>` →
  `{"conversation_id","conversation_name", "messages":[{id,role,content,created_at,tool_calls,needs_attention,read}]}`.
  Used for Keep-chat restore (no after_id) and human-poll (after_id = last seen id; returns only newer).
- `POST /api/instant` body `{conversation_id, name?, message}` →
  detect `^q(\d{1,2})$` (case-insensitive) → if FAQ number exists: persist visitor row (content =
  original message; conversation_name = name if given and not already set) and an avatar row
  (content = `instant_answer_markdown(n)`, tool_calls = `{"instant": n}`), return
  `{"found":true,"question_number":n,"content":<avatar markdown>,"avatar_id":<row id>,"visitor_id":<row id>}`.
  If not found / not a Qn → `{"found":false}` and persist nothing (frontend falls back to /api/chat).
  Apply rate limit + clamp first.
- `POST /api/chat` body `{conversation_id, name?, message}` → **SSE stream**
  (`media_type="text/event-stream"`). Order of operations:
  1. Rate-limit check → if exceeded, return 429 JSON `{"error":"rate_limited"}` (NOT a stream).
  2. Clamp message to `MAX_MESSAGE_CHARS` (+ note) — clamped text is stored AND sent to LLM.
  3. Insert visitor row (set conversation_name if `name` provided and conversation has none yet).
  4. Load full conversation; build user task; run `stream_reply`.
  5. Emit SSE frames `data: <json>\n\n` where json is one of:
     `{"type":"token","text":...}`, `{"type":"tool","phase":"calling|done","name":...,"detail":...}`,
     `{"type":"done","message_id":<avatar row id>}`, `{"type":"error","message":...}`.
  6. On completion, insert avatar row (full text, tool_calls summary) BEFORE emitting `done`
     (so the id is real). If the client disconnects mid-stream, still persist what was generated.

  SSE wire: plain `data:` frames (no custom event names) so the frontend parses with fetch +
  ReadableStream by splitting on `\n\n`. Send an initial `data: {"type":"start"}` if helpful.

### Admin (all under `/admin/*` data routes require `require_admin`)
- `POST /admin/login` body `{password}` → if `== ADMIN_PASSWORD`: set cookie, `{"ok":true}`; else 401
  `{"ok":false}`. (Constant-time compare with `hmac.compare_digest`.)
- `POST /admin/logout` → clear cookie, `{"ok":true}`.
- `GET /admin/me` → `{"ok":true}` if authed (else 401). Frontend uses this to decide gate vs dash.
- `GET /admin/conversations` → `{"conversations":[<summary>...]}` most-recent first (see db.list_conversations).
- `GET /admin/conversations/{conversation_id}` → opens it: marks read in one round-trip (attention
  is left intact, cleared only by /resolve), returns `{"conversation_id","conversation_name","messages":[...]}` (full thread).
- `POST /admin/conversations/{conversation_id}/message` body `{content}` → insert `human` row
  (read=true, needs_attention=false), return `{"message":<row>}`. **Avatar does NOT react.**
- `POST /admin/conversations/{conversation_id}/resolve` → clear needs_attention, `{"ok":true}`.

### Static serving
- Mount built frontend. `GET /` → `STATIC_DIR/index.html`; `GET /admin` → `STATIC_DIR/admin.html`.
  Serve `/assets/*`, `/icons.svg`, `/*.png` from `STATIC_DIR`. Use `StaticFiles` for assets and
  explicit `FileResponse` routes for `/` and `/admin` so they win over the SPA mount. Guard for the
  case where `STATIC_DIR` doesn't exist yet (dev) — return a friendly placeholder, don't crash.
- CORS: not needed in container (same origin). In dev, Vite proxies `/api` and `/admin` to :8000,
  so no CORS required. Do not add permissive CORS.

---

## 9. Frontend wiring

Vite multi-page. `vite.config.ts` `build.rollupOptions.input = { main: 'index.html', admin: 'admin.html' }`,
`server.proxy` maps `/api` and `/admin` → `http://localhost:8000`. Output `dist/` (→ backend STATIC_DIR).
Both `index.html` and `admin.html` set `data-theme` early (inline script reading
`localStorage['avatar-theme']`, default dark) to avoid a flash.

`src/api.ts` (the shared contract used by BOTH screens) exports typed functions:
- `getConfig()`, `getConversation(id, afterId?)`, `postInstant(body)`, `streamChat(body, handlers)`
  (handlers: onToken, onTool, onDone, onError; implemented with fetch + ReadableStream),
- admin: `adminMe()`, `adminLogin(pw)`, `adminLogout()`, `adminListConversations()`,
  `adminOpenConversation(id)`, `adminPostMessage(id, content)`, `adminResolve(id)`.

### Visitor (`index.html` + `src/visitor/main.ts`), target `mockups/Visitor Chat.html`
- Top bar: brand (mark + "Avatar" + owner subtitle from `getConfig().owner_name`), name/initials
  field, **Keep chat** switch (default ON), **Reset**, theme toggle. Page title uses owner name.
- conversation_id: if Keep chat ON, read cookie `avatar_conversation` (SameSite=Lax, ~1yr); if
  present, restore thread via getConversation; else mint a new UUID and set cookie. Reset → clear
  view + new UUID + cookie.
- Composer autofocuses on load and re-focuses after every send (HARD requirement). Enter sends,
  Shift+Enter newline. Suggestion chips (2–3) submit immediately on click.
- Qn shortcut: if `message.trim()` matches `^q\d{1,2}$` → call postInstant; render avatar bubble
  with `.instant-tag` "instant · Q2". If `{found:false}`, fall back to streamChat.
- `?q=N` deep link: on load, if URL has `?q=N`, submit `Q{N}` immediately then clear the param
  from the URL (history.replaceState).
- streamChat: optimistic visitor bubble; show `.tool-status` lines (calling → done) in mono;
  stream tokens into the avatar `.bubble`; on done re-focus composer.
- Polling for human (§E): poll getConversation(id, lastSeenId) every 10s, easing to 60s after 5
  quiet minutes; reset to 10s on visitor send. New `human` rows render as `.msg--human`.
- Footer social links → Quinten's: LinkedIn `https://www.linkedin.com/in/quintenkocian/`,
  GitHub `https://github.com/quintenkocian` (use the sprite icons present in icons.svg; if there's
  no YouTube link for this owner, use GitHub instead of a YouTube link).

### Admin (`admin.html` + `src/admin/main.ts`), target `mockups/Admin Dashboard.html`
- Login gate first: centred card (i-lock, i-shield note, `.btn--primary`). On load call adminMe();
  if 401 show gate, else show dashboard. Login posts password; on success show dashboard.
- Sidebar inbox: adminListConversations(), most-recent first. Row `.convo-item` with initials
  avatar, name, timestamp, preview. `.is-unread` (brighter + `.badge--dot`), `.is-attention`
  (yellow glow + "Needs you" badge — persists until opened), `.is-active`.
- Main panel: thread header (initials, name, `conv_…` id in mono, started time, count, the
  "Avatar asked for you" flag + "Mark resolved" button), full thread, admin composer with the
  "posting as you — visitor sees your photo, no name" note.
- Open thread → adminOpenConversation (clears unread + attention), render, scroll to latest.
- Keyboard: ↑/↓ move selection between conversations, Enter sends, Shift+Enter newline.
- Resolve button → adminResolve.
- Poll the inbox (and the open thread) periodically (~10s) so new visitor activity / attention
  surfaces without reload.
- Mobile master/detail: inbox fills screen; tapping a conversation opens the thread (scrolled to
  latest) with a back control; desktop side-by-side unchanged.

### Roles rendering (both screens; see design-system §4)
- Visitor: `.msg--visitor`, right aligned, `.avatar-initials` (blue token from name/initials).
- Avatar: `.msg--avatar`, left, `avatar-robot-round.png` in `.avatar-twin` (cyan ring), name
  "Avatar", `.tool-status` lines above bubble.
- Human: `.msg--human`, left, `avatar-human.png` in `.avatar-human` (yellow ring + tint + glow),
  labelled **`{owner_name} · live`** (owner_name from getConfig) — see Resolved conflicts.

---

## 10. Infra

- **Dockerfile** (multi-stage):
  - Stage `web`: `node:24-alpine`, copy `frontend/`, `npm ci`, `npm run build` → `/frontend/dist`.
  - Stage `app`: `python:3.12-slim`, install `uv`, copy `backend/`, `uv sync --frozen`, copy
    `knowledge/`, copy built `dist` from `web` stage to `/app/static`. Set `KNOWLEDGE_DIR=/app/knowledge`,
    `STATIC_DIR=/app/static`, `PORT=8000`. CMD: `uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}`
    run with `--app-dir backend` or copy backend into workdir so `app.main` resolves.
  - `.dockerignore`: `.env`, `**/.venv`, `node_modules`, `dist`, `__pycache__`, screenshots, `.git`.
- **scripts/start_pc.ps1 / stop_pc.ps1**: stop+rm `avatar` container if running, `docker build -t avatar .`,
  `docker run -d --name avatar --env-file .env -p 8000:8000 avatar`. start scripts rebuild every time.
- **scripts/start_mac.sh / stop_mac.sh**: bash equivalents. All four scripts take `.env` from repo root.
- **scripts/fly.toml, deploy.sh, wordpress-embed.html**: per DEPLOY.md (already specified there);
  app name `avatar-quinten` placeholder, region near Supabase. Keep DEPLOY.md and these consistent.

---

## 11. Resolved conflicts (SPEC vs design-system)

1. **Human bubble label.** design-system/SKILL.md says "name-free (The human · live)". SPEC Q&A #4
   (updated) + #11 say show the owner name from `OWNER_NAME`, e.g. `"Ed Donner - live"`.
   **SPEC wins (behaviour):** render `{owner_name} · live`, sourced from `/api/config`. Never hardcode.
2. **Active inbox row left bar** (`.convo-item.is-active::before`) is allowed (selection indicator),
   per the design-system Notes. Keep it.
3. **Avatar images:** use the shipped `design-system/assets/*.png` as-is (SPEC says treat them as
   source of truth; do not re-derive). Copy into `frontend/public/`.

---

## 12. Testing contract (test/ + tests/)

- Backend unit tests with `uv run pytest`. Cover: knowledge loading + faq + instant format;
  security (token sign/verify, admin routes 401 without cookie, 200 with); rate limit (21st → 429);
  config; public API (instant Qn persists 2 rows; chat streams + persists avatar row; conversation
  fetch + after_id; clamp >20000). LLM-touching tests marked `@pytest.mark.llm` and use nano.
- conftest cleans up any test conversation rows it creates (and a known TEST uuid prefix).
- Frontend/E2E with Playwright: screenshots of both screens, dark+light, desktop+mobile, every
  state in the states matrix. Three-way flow end-to-end. Delete screenshots + test Supabase rows
  when done. Document plans with checkboxes in `test/` and check them off.
```
