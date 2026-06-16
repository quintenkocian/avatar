# MORE Test Plan

Verification for the "MORE" evolution (see `MORE.md`): admin **Archive**,
**Instructions** and a Supabase-backed **FAQ** editor; a job-posting web-fetch
MCP tool; the `?m=` deep link; the 4-tier visitor polling ladder; the OG image;
and the post-build refinements + security hardening.

**Production-data safety (MORE.md #13).** There is only one Supabase database and
it is production. Before any archive/delete work all 128 existing rows were backed
up to `backups/messages_backup_20260615.jsonl`. Every test used throwaway
`conversation_id`s and cleaned up afterwards. After testing, all 128 real rows
were confirmed **byte-identical** to the backup. The real 72h bulk-archive was
**never executed** against the live DB (13 real conversations are >72h old); its
selection logic is covered by unit tests + a non-mutating live check instead.

## How to run

```
# Backend (hermetic + live + connectivity)
cd backend
uv run pytest -q -m "not llm"                          # 131 hermetic tests
uv run pytest tests/test_supabase_connection.py -v     # 4-table connectivity gate
uv run pytest -m llm -q                                 # live model + Supabase

# FAQ seed (idempotent) and OG image
cd backend && uv run python ../scripts/seed_faq.py
uv run --with pillow python scripts/generate_og.py

# Frontend
cd frontend
npx tsc --noEmit && npx vite build                      # typecheck + production build
npx playwright test                                     # e2e (needs a Playwright browser)
cd backend && uv run python ../test/cleanup_e2e.py      # sweep e2e conversations (both tables)
```

> **Environment note.** This machine is `ubuntu26.04-arm64`, for which Playwright
> ships no browser build, so the browser-driven checks below were executed via
> Windows Chromium (screenshots) and the API checks via `curl`/Python against the
> running Docker container. The `frontend/e2e/more.spec.ts` specs encode the same
> flows for any environment that has a Playwright browser.

## Archive functionality

- [x] `archive` table created (same shape as `messages`) + indexes + grant
- [x] Thread-level **Archive** button archives the whole conversation (copy to
      `archive`, delete from `messages`) — verified live + via UI
- [x] Archived conversation leaves the Conversations inbox and appears in Archive
- [x] **Restore** moves the whole conversation back to the live inbox
- [x] `created_at`, `conversation_name` and tool calls are preserved across the
      round-trip; `id` is reassigned by the destination table
- [x] Open an archived thread is **read-only** (no read/attention side effects)
- [x] 72h bulk-archive: selection logic unit-tested (`_latest_at_by_conversation`,
      `_parse_ts`) + non-mutating live check; **not** executed against live data
- [x] All admin archive routes require a valid session (401 without)

## Download + total

- [x] Conversations page: **Download** exports one JSON object per message row as
      JSONL with `Content-Disposition: attachment; filename="conversations.jsonl"`
- [x] Archive page: **Download** → `archive.jsonl`
- [x] Total conversation count shown near the top of each page (count badge)

## Polling frequency

- [x] 4-tier ladder: 10s, → 30s after 2 min idle, → 2 min after 10 min, → 5 min
      after 1 hr (`intervalForIdle` + `POLL_TIERS`)
- [x] Idle resets on a send AND on a received human message (`noteActivity`)
- [x] Old 10s/60s scheme fully replaced

## Additional instructions

- [x] `settings` table (single pinned row id=1) created
- [x] Admin **Instructions** tab loads current value, edits, saves
- [x] Read fresh on every chat turn (not cached) — injected **last** in the prompt
      (cache-friendly), after the style/rules sections
- [x] Empty by default; save round-trips (UI + API verified)

## FAQ → Supabase

- [x] `faq` table (id, concise, question, answer) created
- [x] Seeded 18 rows from `faq.jsonl`, ids 1–18 preserved (`Qn` / `?q=N` resolve)
- [x] Admin **FAQ** tab: list, add (id = max+1), edit, delete
- [x] FAQ markdown hygiene (underscore identifiers → inline code, image notes
      stripped) — dataset already clean; seeder applies it defensively
- [x] DB is source of truth; `faq.jsonl` kept as seed/backup; seed reachable in
      the connectivity gate

## Web fetch (MCP) for job-post links

- [x] `mcp-server-fetch` pre-installed (dependency in the image, on PATH)
- [x] MCP server starts per chat turn and exposes the `fetch` tool
- [x] INSTRUCTIONS scope the tool to job postings only (no general browsing);
      verifies the page is a job posting
- [x] End-to-end: a linked job description is fetched and an honest fit analysis
      is produced (validated against a deterministic local server)
- [x] Fetch tool-use shows in the UI alongside `faq_tool` and `push_tool`
      (`i-globe` icon, "Read the linked job posting")
- [x] If the MCP server can't start, the turn proceeds with the other tools

## OG social image

- [x] `og-avatar.png` (1200×630) generated in the project root from the avatar
      assets + brand palette; owner-aware (name from `OWNER_NAME`)
- [x] Not served by the app; no `og:image` meta tags added

## `?m=` query parameter

- [x] `?m=text` read from `location.search`, cleared via `replaceState`,
      auto-submitted as a normal (LLM) message
- [x] If both `?q=N` and `?m=` present, `?q` wins (instant FAQ, no LLM)

## Post-build refinements

- [x] `rules.md` split out of `style.md` (owner-agnostic operating rules)
- [x] All knowledge files start headings at `##` (nest under the prompt's `#`)
- [x] `ModelSettings(max_tokens=2000)` hard cap + graceful "kept it brief" note on
      truncation (detected via the last response's token usage)
- [x] Additional-instructions block placed last in the system prompt

## Security hardening

- [x] Fail closed: app refuses to start without `ADMIN_PASSWORD`; no public
      `avatar::` session-secret fallback
- [x] Admin login throttled per IP (5/min); successful logins never throttled
      (verified: 5×401 → 429)
- [x] Transcript bounded to recent messages within a char budget (full history
      still stored)
- [x] Pushover: short timeout + soft failure; high priority; `bugle` for
      human-in-the-loop, `gamelan` for backend-error and failed-login alerts
- [x] Error alerts debounced per category; failed-login alerts un-debounced
      (bounded by the login throttle)

## Cross-cutting

- [x] Docker image builds (frontend bundled, deps incl. `mcp-server-fetch`) and
      runs healthy; all admin API routes verified against the container
- [x] 12 UI screenshots (desktop + mobile, dark + light): 4-tab nav, archive
      flow, FAQ editor, instructions, instant `?q=2`
- [x] Backend: 131 hermetic + 6 connectivity tests pass; live agent + live fetch
      validated
- [x] Production DB confirmed pristine after all testing (128 rows == backup)
