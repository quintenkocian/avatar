# Avatar — Build Architecture & Interface Contract

This is the shared, authoritative contract for the implementation. It pins down the
file layout, the exact HTTP API shapes, the SSE wire format, the agent prompt, and the
frontend wiring so that independently-built modules fit together with no drift.

**Authority:** `SPEC.md` wins on behaviour/backend; `design-system/` wins on look/feel.
Where they conflict, this doc records the resolution (see "Resolved conflicts").
Behavioural additions from the **MORE evolution** (`MORE.md`) are folded into the relevant
sections below (admin Archive / Instructions / FAQ tabs, the web-fetch MCP tool, the `?m=`
deep link, the polling ladder, and the security hardening).

Owner for this build: **Quinten Kocian** (from `OWNER_NAME` env — never hardcode it).
Model for dev/test: `openai/gpt-5.4-nano`; the reference deployment uses `openai/gpt-5.4-mini`
(the web-fetch feature is exercised with mini). Both come from `MODEL` in `.env`.

---

## 1. Repository layout (target)

```
backend/
  app/
    __init__.py
    config.py          # env settings, paths, constants; require_admin_password() fail-closed
    models.py          # pydantic request/response models (+ Instructions/Faq request bodies)
    knowledge.py       # load knowledge.md/style.md/rules.md; compose prompt; FAQ formatting (FAQ data comes from db)
    db.py              # Supabase data-access layer: messages + archive + settings + faq tables
    security.py        # admin session cookie sign/verify (itsdangerous), auth dependency
    rate_limit.py      # limits moving-window: chat per conversation_id + failed-login per IP
    notifications.py   # Pushover: human ping + debounced backend-error / failed-login alerts
    agent.py           # OpenAI Agents SDK + OpenRouter, FAQ/push tools + fetch MCP, streaming
    main.py            # FastAPI app: public + admin routes (incl. MORE) + static serving
  tests/
    test_supabase_connection.py   # EXISTS — connectivity gate, now covers all 4 tables
    test_knowledge.py
    test_security.py
    test_rate_limit.py
    test_config.py
    test_db_helpers.py
    test_api_public.py            # chat/instant/conversation (nano model OK)
    test_api_admin.py             # auth gating, login, thread open, post, resolve, archive/faq/etc.
    test_api_more.py              # archive/instructions/faq/export routes + login throttle
    test_notifications.py         # Pushover priority/sounds + error debounce
    conftest.py                   # shared fixtures (TestClient, FakeDB, cleanup of test rows)
  pyproject.toml       # EXISTS (deps incl. mcp-server-fetch)
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
    og-avatar.png             # 1200x630 OG card; bundled & served at /og-avatar.png
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
    admin/main.ts      # admin screen logic (4-tab nav: Conversations|Archive|Instructions|FAQ)
  e2e/                 # Playwright specs: visitor / admin / three-way / more
Dockerfile             # multi-stage: node build frontend -> python run backend
.dockerignore
scripts/
  start_pc.ps1  stop_pc.ps1  start_mac.sh  stop_mac.sh
  deploy.sh  fly.toml  wordpress-embed.html
  seed_faq.py          # upsert knowledge/faq.jsonl -> Supabase faq table (idempotent)
  generate_og.py       # build frontend/public/og-avatar.png from avatar assets + OWNER_NAME
test/
  backend-test-plan.md       # checkbox plan
  frontend-test-plan.md
  e2e-test-plan.md
  more-test-plan.md          # MORE features + production-data safety
  cleanup_e2e.py             # delete e2e conversations (sweeps messages + archive)
docs/ARCHITECTURE.md   # this file
```

`reference/` is inspiration only — do NOT import from it (`reference/fetch.ipynb` is the
web-fetch MCP reference). `pypdf` is NOT a dependency.

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
- `SESSION_SECRET: str` — default `f"avatar::{ADMIN_PASSWORD}"` if unset (safe because the app
  refuses to start with an empty `ADMIN_PASSWORD`, so the public `avatar::` constant never occurs)
- `COOKIE_SECURE: bool` — from `COOKIE_SECURE` == "1"
- `KNOWLEDGE_DIR: Path` — env `KNOWLEDGE_DIR` or default project_root/`knowledge`
- `STATIC_DIR: Path` — env `STATIC_DIR` or default project_root/`frontend/dist`
- `OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"`
- `MODEL_MAX_TOKENS: int = 2000` — hard per-reply output ceiling (see §5).
- `TRANSCRIPT_CHAR_BUDGET: int = 24000` — per-turn transcript bound (see §4).
- `FETCH_MCP_COMMAND` / `FETCH_MCP_ARGS` — web-fetch MCP launcher (default `uvx mcp-server-fetch`;
  empty `FETCH_MCP_COMMAND` disables fetch). A pre-installed `mcp-server-fetch` on PATH is preferred.
- `LOGIN_RATE_LIMIT: str = "5/minute"` — per-IP cap on FAILED admin logins.
- Constants: `MAX_MESSAGE_CHARS = 20000`, `TRUNCATION_NOTE = "\n\n[...message truncated as it's too long; ask the visitor to send something more concise]"`, `RATE_LIMIT = "20/minute"`.

`config.require_admin_password()` raises `RuntimeError` if `ADMIN_PASSWORD` is empty; it is called
from the FastAPI lifespan at startup so the app **fails closed** rather than running insecurely.

`OPENROUTER_BASE_URL` etc. must come from config, not be scattered.

---

## 3. Data layer (`db.py`)

One lazily-created module-level Supabase `Client` (`create_client(SUPABASE_URL, SUPABASE_KEY)`).
`_table(name=TABLE)` selects a table. Four tables (all created via the Supabase SQL editor,
granted to `service_role`, **no RLS** — see the README "Setup for MORE requirements"):

- **`messages`** — `id` (bigint identity), `conversation_id` (uuid str), `conversation_name`
  (text|null), `role` ('visitor'|'avatar'|'human'), `content` (text), `tool_calls` (jsonb|null),
  `needs_attention` (bool), `read` (bool), `created_at` (timestamptz).
- **`archive`** — identical shape to `messages`. A whole conversation is moved here when archived.
- **`settings`** — single pinned row `id=1`: `additional_instructions` (text), `updated_at`.
- **`faq`** — `id` (bigint = FAQ number), `concise` (routing phrase), `question`, `answer`.

Functions (all synchronous; FastAPI wraps them with `run_in_threadpool`):

- `insert_message(conversation_id, role, content, *, conversation_name=None, tool_calls=None, needs_attention=False, read=False) -> dict` — returns inserted row.
- `get_conversation(conversation_id, after_id=None, *, table=TABLE) -> list[dict]` — rows for a
  conversation ordered `created_at asc` (tiebreak `id asc`); if `after_id`, only `id > after_id`.
  `table` selects `messages` (default) or `archive`.
- `get_conversation_name(conversation_id) -> str | None` — derive from rows already fetched
  where possible; helper only.
- `list_conversations(*, table=TABLE) -> list[dict]` — one query of all rows ordered
  `created_at desc`, grouped in Python into summaries (most-recent first). Each summary:
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
- `delete_conversation(conversation_id, *, table=TABLE) -> None` — test cleanup helper.

**MORE — archive / restore** (whole-conversation moves; copy-then-delete so a failure can never
lose data, at worst leaving a duplicate in the destination):

- `archive_conversation(conversation_id) -> int` — copy rows `messages → archive`, delete from
  `messages`; returns count. `created_at` and other columns are preserved; `id` is reassigned.
- `restore_conversation(conversation_id) -> int` — the reverse (`archive → messages`).
- `list_archived_conversations() -> list[dict]` / `get_archived_conversation(id) -> list[dict]` —
  archive equivalents of `list_conversations` / `get_conversation`.
- `archive_inactive(hours=72, *, now=None) -> list[str]` — archive every conversation whose newest
  message is older than the cutoff; returns the archived ids. (Selection via
  `_latest_at_by_conversation` + `_parse_ts`.)

**MORE — counts / export / settings / faq:**

- `count_conversations(*, table=TABLE) -> int`; `export_rows(*, table=TABLE) -> list[dict]` (all
  rows in chronological order, for the JSONL download).
- `get_additional_instructions() -> str` (soft-fails to `""`); `set_additional_instructions(text) -> str`
  (upsert the single `settings` row id=1).
- `list_faqs() -> list[dict]`, `get_faq(id) -> dict|None`, `create_faq(concise, question, answer) -> dict`
  (id = `max(id)+1`), `update_faq(id, concise, question, answer) -> dict|None`, `delete_faq(id)`,
  `upsert_faq(id, ...)` (seeding). Rows are normalised to `{id, concise, question, answer}`.

Use the supabase-py v2 sync client. Handle the deprecation warnings already seen (harmless).

---

## 4. Knowledge & prompt (`knowledge.py`)

Owner knowledge is now **three** files, each one job: `knowledge.md` (facts), `style.md` (voice +
formatting), `rules.md` (owner-agnostic operating rules: safety, escalation, answer length). Each
starts its headings at `##` so they nest under the prompt's `#` sections. This module is **pure**
(no DB import): FAQ data is passed in by the caller, sourced from `db.list_faqs()`.

- Load on import (cache): `knowledge.md`, `style.md`, `rules.md` from `KNOWLEDGE_DIR`.
- `SEED_FAQS: list[dict]` + `SEED_FAQ_BY_ID` — `faq.jsonl` normalised to `{id, concise, question,
  answer}`, used as a **fallback** when the DB FAQ is empty/unreachable. `seed_faq(id) -> dict|None`.
- `format_faq_answer(row) -> str` — `"### Question {id}\n{question}\n\n### Answer\n{answer}"`
  (for `faq_tool`). `format_instant(row) -> str` — the visitor-facing `Qn` body
  `f"**Q{id}:** {question}\n\n{answer}"` (restates the question, per SPEC).
- `build_fetch_instructions(owner_name) -> str` — the narrowly-scoped operating rules for the
  fetch tool: use it ONLY to read a job posting a visitor links; verify it's a job posting; give an
  honest fit assessment; never general browsing (see §5).
- `build_system_prompt(owner_name, faqs=None, *, additional_instructions=None) -> str` — composes,
  in order:
  1. Role + the THREE-WAY setup (visitor / avatar / the real human `{owner_name}` who may join;
     their messages are labelled and already in the transcript — build on them, never impersonate).
  2. `knowledge.md`.  3. `style.md`.  4. `rules.md`.
  5. FAQ routing block: list each FAQ as `\n{id}. {concise}` (from `faqs`, falling back to
     `SEED_FAQS`); relay `faq_tool` answers verbatim in markdown.
  6. Tools block: `faq_tool(question_number:int)`, `push_tool(message:str)`, and `fetch` (scoped).
  7. Fetch / job-description instructions (`build_fetch_instructions`).
  8. **LAST:** the admin's `additional_instructions` (if non-empty) — placed after the long static
     prefix so prompt caching stays effective and the editable block gains recency emphasis.
- `build_user_task(messages, owner_name, pending_visitor=None) -> str` — renders the conversation
  as ONE user task, labelling roles `Visitor` / `Avatar (you)` / `{owner_name} (the human)`. The
  transcript is **bounded** to the most recent messages within `settings.TRANSCRIPT_CHAR_BUDGET`
  (the latest visitor line is always kept; older lines are dropped with a note). The full history is
  still stored — only what's sent to the model is bounded.

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

- `faq_tool(question_number: int) -> str` — looks up `db.get_faq(n)` (falling back to
  `knowledge.seed_faq`), formats via `knowledge.format_faq_answer`.
- `push_tool(message: str) -> str` — delegates to `notifications.push_human` (soft-fails).
- **Fetch MCP** — `_fetch_mcp_params()` resolves the stdio launcher (prefers a pre-installed
  `mcp-server-fetch` on PATH, else `uvx mcp-server-fetch`; `None` disables it). The server
  (`MCPServerStdio`, `cache_tools_list=True`, 240s timeout) is `connect()`-ed per chat turn and
  `cleanup()`-ed in `finally`; if it can't start, the turn proceeds with just FAQ + push tools.
- `build_agent(owner_name, system_prompt=None, *, mcp_servers=None) -> Agent` —
  `instructions=system_prompt` (caller passes the composed prompt), `model=_model`,
  `model_settings=ModelSettings(max_tokens=settings.MODEL_MAX_TOKENS)`, `tools=[faq_tool, push_tool]`,
  `mcp_servers=...`.
- `async def stream_reply(task, owner_name, system_prompt=None) -> AsyncIterator[StreamPiece]` —
  starts the fetch MCP (best effort), builds the agent, runs `Runner.run_streamed` and yields:
  - `{"type":"token","text": delta}` for `raw_response_event` + `ResponseTextDeltaEvent`
  - `{"type":"tool","phase":"calling|done","name": tool_name,"detail": optional}` on tool events
  - `{"type":"error","message": ...}` on failure (also fires `notifications.push_error("chat", …)`).
  On a clean finish, if the last response hit the `max_tokens` ceiling, a final token piece appends
  a graceful "kept it brief" note (so it's persisted with the reply). The caller accumulates the
  full text + tool_calls for persistence.

Tool-status detail mapping for the UI: FAQ number (`Q10`), pushed-message preview, or the fetched
`url` — include the tool name; the detail is nice-to-have. Fetch tool-use renders with the
`i-globe` icon ("Read the linked job posting").

---

## 6. Security (`security.py`)

- `itsdangerous.TimestampSigner` (or URLSafeTimedSerializer) keyed by `SESSION_SECRET`.
- `make_session_token() -> str` and `verify_session_token(token) -> bool` (max_age e.g. 7 days).
- Cookie name `avatar_admin`, `httponly=True`, `samesite="lax"`, `secure=settings.COOKIE_SECURE`,
  `path="/"`.
- FastAPI dependency `require_admin(request)` → 401 if cookie missing/invalid. Guards every
  `/admin/*` data route (NOT `/admin` static page, NOT `/admin/login`).
- `check_password` uses `hmac.compare_digest` and returns False when `ADMIN_PASSWORD` is unset.
  Startup additionally **fails closed**: `config.require_admin_password()` (called from the lifespan)
  raises if `ADMIN_PASSWORD` is empty, so the app never runs with a forgeable session secret.

---

## 7. Rate limit (`rate_limit.py`)

- `limits` moving-window, in-memory storage.
- `check(conversation_id) -> bool` — `20/minute` per `conversation_id`. Used in chat + instant
  BEFORE any model call. On False the route returns HTTP 429 `{"error":"rate_limited"}`.
- `login_check(client_ip) -> bool` — `LOGIN_RATE_LIMIT` (5/minute) per IP, consumed only on a
  FAILED admin login. On False `/admin/login` returns 429 `{"ok":false,"error":"too_many_attempts"}`.
  Successful logins are never counted, so the owner is never locked out; per-IP keying means an
  attacker only locks their own IP.

## Notifications (`notifications.py`)

Pushover, centralised. All pushes are high priority (`priority: 1`, bypassing quiet hours), with a
short timeout, and **fail soft** (a slow/unreachable Pushover never hangs a request).

- `push_human(message) -> str` — human-in-the-loop ping (sound `bugle`); used by `push_tool`.
  Returns a benign status string for the agent. No-op-with-log if creds are missing.
- `push_error(category, detail) -> None` — backend-error alert (sound `gamelan`), **debounced** per
  category (a few/hour). Fired on a chat-run failure and other unhandled server errors.
- `push_login_failure(client_ip) -> None` — failed-login alert (sound `gamelan`), **not** debounced
  (bounded instead by the per-IP login throttle).

---

## 8. HTTP API (`main.py`)

All JSON unless noted. `conversation_id` is a client-minted UUID string.

### Public
- `GET /api/config` → `{"owner_name": settings.OWNER_NAME}` — no DB. (Fly health check path.)
- `GET /api/conversation?conversation_id=<uuid>&after_id=<int?>` →
  `{"conversation_id","conversation_name", "messages":[{id,role,content,created_at,tool_calls,needs_attention,read}]}`.
  Used for Keep-chat restore (no after_id) and human-poll (after_id = last seen id; returns only newer).
- `POST /api/instant` body `{conversation_id, name?, message}` →
  detect `^q(\d{1,2})$` (case-insensitive) → look up the FAQ via `db.get_faq(n)` (falling back to
  `knowledge.seed_faq`); if found: persist visitor row (content = original message; conversation_name
  = name if given and not already set) and an avatar row (content = `knowledge.format_instant(row)`,
  tool_calls = `{"instant": n}`), return
  `{"found":true,"question_number":n,"content":<avatar markdown>,"avatar_id":<row id>,"visitor_id":<row id>}`.
  If not found / not a Qn → `{"found":false}` and persist nothing (frontend falls back to /api/chat).
  Apply rate limit + clamp first.
- `POST /api/chat` body `{conversation_id, name?, message}` → **SSE stream**
  (`media_type="text/event-stream"`). Order of operations:
  1. Rate-limit check → if exceeded, return 429 JSON `{"error":"rate_limited"}` (NOT a stream).
  2. Clamp message to `MAX_MESSAGE_CHARS` (+ note) — clamped text is stored AND sent to LLM.
  3. Insert visitor row (set conversation_name if `name` provided and conversation has none yet).
  4. Load full conversation; build the (bounded) user task. Compose the system prompt from the
     **live** FAQ list (`db.list_faqs`, seed fallback) and the admin's `additional_instructions`
     (`db.get_additional_instructions`) — both read fresh so edits take effect immediately — and pass
     it to `stream_reply(task, owner, system_prompt=…)`.
  5. Emit SSE frames `data: <json>\n\n` where json is one of:
     `{"type":"token","text":...}`, `{"type":"tool","phase":"calling|done","name":...,"detail":...}`,
     `{"type":"done","message_id":<avatar row id>}`, `{"type":"error","message":...}`.
  6. On completion, insert avatar row (full text, tool_calls summary) BEFORE emitting `done`
     (so the id is real). If the client disconnects mid-stream, still persist what was generated.

  SSE wire: plain `data:` frames (no custom event names) so the frontend parses with fetch +
  ReadableStream by splitting on `\n\n`. Send an initial `data: {"type":"start"}` if helpful.

### Admin (all under `/admin/*` data routes require `require_admin`)
- `POST /admin/login` body `{password}` → per-IP `login_check` first (429 `{"ok":false,
  "error":"too_many_attempts"}` once over the failed-attempt cap); then if `== ADMIN_PASSWORD`: set
  cookie, `{"ok":true}`; else `push_login_failure(ip)` + 401 `{"ok":false}`. (Constant-time compare.)
- `POST /admin/logout` → clear cookie, `{"ok":true}`.
- `GET /admin/me` → `{"ok":true}` if authed (else 401). Frontend uses this to decide gate vs dash.
- `GET /admin/conversations` → `{"conversations":[<summary>...]}` most-recent first (see db.list_conversations).
- `GET /admin/conversations/{conversation_id}` → opens it: marks read in one round-trip (attention
  is left intact, cleared only by /resolve), returns `{"conversation_id","conversation_name","messages":[...]}` (full thread).
- `POST /admin/conversations/{conversation_id}/message` body `{content}` → insert `human` row
  (read=true, needs_attention=false), return `{"message":<row>}`. **Avatar does NOT react.**
- `POST /admin/conversations/{conversation_id}/resolve` → clear needs_attention, `{"ok":true}`.

#### MORE admin routes
- `POST /admin/conversations/{id}/archive` → archive the whole conversation, `{"ok":true,"moved":n}`.
- `GET /admin/archive` → `{"conversations":[<summary>...],"total":n}` (archive inbox).
- `GET /admin/archive/{id}` → open an archived thread **read-only** (no read/attention side effects):
  `{"conversation_id","conversation_name","messages":[...]}`.
- `POST /admin/archive/{id}/restore` → move it back to the live inbox, `{"ok":true,"moved":n}`.
- `POST /admin/archive-inactive` → archive everything idle 72h+, `{"ok":true,"archived":[ids],"count":n}`.
- `GET /admin/export/conversations` · `GET /admin/export/archive` → JSONL download (one JSON object
  per message row) with `Content-Disposition: attachment; filename="…jsonl"`.
- `GET /admin/instructions` → `{"additional_instructions": str}`;
  `PUT /admin/instructions` body `{additional_instructions}` → save, returns the stored value.
- `GET /admin/faq` → `{"faqs":[{id,concise,question,answer}...],"total":n}`;
  `POST /admin/faq` body `{concise?,question,answer}` → `{"faq":<row>}` (id auto-assigned);
  `PUT /admin/faq/{id}` → `{"faq":<row>}` (404 if absent); `DELETE /admin/faq/{id}` → `{"ok":true}`.

### Static serving
- Mount built frontend. `GET /` → `STATIC_DIR/index.html` (rewriting the page's root-relative
  `og:image`/`twitter:image`/`og:url` to absolute URLs from the request host or `PUBLIC_BASE_URL`,
  since social scrapers require absolute Open Graph URLs); `GET /admin` → `STATIC_DIR/admin.html`.
  Serve `/assets/*`, `/icons.svg`, `/*.png` (incl. `/og-avatar.png`) from `STATIC_DIR`. Use `StaticFiles` for assets and
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
  `adminOpenConversation(id)`, `adminPostMessage(id, content)`, `adminResolve(id)`,
- admin (MORE): `adminArchiveConversation(id)`, `adminListArchive()`, `adminOpenArchive(id)`,
  `adminRestoreConversation(id)`, `adminArchiveInactive()`, `adminGetInstructions()`,
  `adminPutInstructions(text)`, `adminListFaq()`, `adminCreateFaq(body)`, `adminUpdateFaq(id, body)`,
  `adminDeleteFaq(id)`, `adminDownload(path, filename)` (fetch-blob with the session cookie).

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
- Deep links (read from `location.search`, cleared via `history.replaceState`, then auto-submitted):
  `?q=N` submits `Q{N}` (instant FAQ, no LLM); `?m=text` submits free text (routed to the LLM). If
  both are present, **`?q` wins**.
- streamChat: optimistic visitor bubble; show `.tool-status` lines (calling → done) in mono;
  stream tokens into the avatar `.bubble`; on done re-focus composer.
- Polling for human (§E): a 4-tier ladder via `getConversation(id, lastSeenId)` —
  **10s**, easing to **30s after 2 quiet min**, **2m after 10 min**, **5m after 1 hr**. Idle resets
  (back to 10s) on a visitor send AND on a received `human` message. New `human` rows render as
  `.msg--human`.
- Footer social links → Quinten's: LinkedIn `https://www.linkedin.com/in/quintenkocian/`,
  GitHub `https://github.com/quintenkocian` (use the sprite icons present in icons.svg; if there's
  no YouTube link for this owner, use GitHub instead of a YouTube link).

### Admin (`admin.html` + `src/admin/main.ts`), target `mockups/Admin Dashboard.html`
- Login gate first: centred card (i-lock, i-shield note, `.btn--primary`). On load call adminMe();
  if 401 show gate, else show dashboard. Login posts password; on success show dashboard.
- **Main nav** (`.admin-tabs`, a horizontal strip below the appbar, responsive/scrollable on
  mobile): `Conversations | Archive | Instructions | FAQ`. `switchTab` toggles `.tab-panel`
  visibility and resets the mobile master/detail flip; Archive refreshes on open, Instructions/FAQ
  lazy-load once. Arrow-key nav + the open-thread poll are scoped to the Conversations tab.
- **Conversations tab** — sidebar inbox: adminListConversations(), most-recent first. Row
  `.convo-item` with initials avatar, name, timestamp, preview. `.is-unread` (brighter +
  `.badge--dot`), `.is-attention` (yellow glow + "Needs you" badge — persists until **Mark
  resolved**), `.is-active`. Sidebar tools: **Download** (JSONL) + **Archive idle 72h**. Thread
  header: initials, name, `conv_…` id (mono), started time, count, the "Avatar asked for you" flag,
  **Mark resolved**, and **Archive** (archives the whole conversation). Composer posts a `human` row.
  Open thread → adminOpenConversation (marks unread→read; **attention persists** until Mark
  resolved), render, scroll to latest. Keyboard: ↑/↓ move selection, Enter sends, Shift+Enter
  newline. Poll the inbox + open thread (~10s).
- **Archive tab** — its own sidebar/thread (read-only). List + search + **Download**; open an
  archived thread; **Restore** moves it back to the live inbox.
- **Instructions tab** — markdown textarea: `adminGetInstructions` on open, `adminPutInstructions`
  to save (takes effect on the next reply).
- **FAQ tab** — editor over `adminListFaq`: each row is `#id` + concise/question/answer with
  **Save**; **Add question** prepends a new row (id assigned on save); delete per row.
- Mobile master/detail: inbox fills screen; tapping a conversation opens the thread (scrolled to
  latest) with a back control; desktop side-by-side unchanged. Applies to Conversations + Archive.

### Roles rendering (both screens; see design-system §4)
- Visitor: `.msg--visitor`, right aligned, `.avatar-initials` (blue token from name/initials).
- Avatar: `.msg--avatar`, left, `avatar-robot-round.png` in `.avatar-twin` (cyan ring), name
  "Avatar", `.tool-status` lines above bubble (faq → i-check, push → i-mail, fetch → i-globe).
- Human: `.msg--human`, left, `avatar-human.png` in `.avatar-human` (yellow ring + tint + glow),
  labelled **`{owner_name} · live`** (owner_name from getConfig) — see Resolved conflicts.

---

## 10. Infra

- **Dockerfile** (multi-stage):
  - Stage `web`: `node:24-alpine`, copy `frontend/`, `npm ci`, `npm run build` → `/frontend/dist`.
  - Stage `app`: `python:3.12-slim`, install `uv`, copy `backend/`, `uv sync --frozen`, copy
    `knowledge/`, copy built `dist` from `web` stage to `/app/static`. Set `KNOWLEDGE_DIR=/app/knowledge`,
    `STATIC_DIR=/app/static`, `PORT=8000`, `PATH=/app/.venv/bin:$PATH`. `mcp-server-fetch` is a
    backend dependency, so `uv sync` pre-installs it into `/app/.venv/bin` (on PATH) — no runtime
    download for the fetch tool. CMD: `uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --app-dir .`.
  - `.dockerignore`: `.env`, `**/.venv`, `node_modules`, `dist`, `__pycache__`, screenshots, `.git`,
    plus `backups/` (local-only artifact) and `MORE.md`. (`og-avatar.png` now lives in
    `frontend/public/` so the build bundles and serves it.)
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

- Backend unit tests with `uv run pytest` (hermetic; DB + agent + notifications mocked via
  `conftest.FakeDB` / fakes). Cover: knowledge loading + FAQ formatting + prompt composition
  (rules/fetch/instructions sections, transcript bound); security (token sign/verify, fail-closed
  password, admin routes 401 without cookie); rate limit (21st → 429); config; public API; the MORE
  admin routes (`test_api_more.py`: archive/restore/instructions/faq/export + login throttle);
  notifications (`test_notifications.py`: priority/sounds + error debounce). LLM-touching tests are
  `@pytest.mark.llm` and use nano.
- `test_supabase_connection.py` is the **setup gate** — it now checks all four tables
  (`messages`, `archive`, `settings`, `faq`) so the connectivity test fails clearly if the MORE SQL
  hasn't been run.
- conftest / `test/cleanup_e2e.py` clean up test conversation rows (the latter sweeps both
  `messages` and `archive`). **Production safety:** the single Supabase DB is production — back up
  before archive/delete work, use throwaway ids, and never run the real 72h bulk-archive against it.
- Frontend/E2E with Playwright (`frontend/e2e/*.spec.ts`, incl. `more.spec.ts`: tabs, archive/
  restore, instructions, FAQ CRUD, `?m=`): screenshots of both screens, dark+light, desktop+mobile,
  every state in the matrix; three-way flow end-to-end. Delete screenshots + test Supabase rows when
  done. Document plans with checkboxes in `test/` (`more-test-plan.md` for MORE) and check them off.
```
