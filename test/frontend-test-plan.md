# Frontend E2E Test Plan (Playwright)

End-to-end browser tests for the visitor chat and the admin dashboard, run with
Playwright against the **production build served by the FastAPI backend** at
`http://127.0.0.1:8000` (the same artifact the Docker container ships). Two
projects exercise both form factors:

- **desktop** — Chromium, 1280×860
- **mobile** — Pixel 5 (393×851)

Every test runs in dark and/or light, takes screenshots into
`test/screenshots/`, and mints a fresh conversation UUID recorded for cleanup.

## How to run

```
# Backend serving the built dist on :8000 must be up first:
cd backend && uv run uvicorn app.main:app --port 8000      # (or the Docker container)

cd frontend
npx playwright test                         # both projects
npx playwright test --project=desktop       # one project
```

Cleanup after the run (deletes the Supabase rows the suite created):

```
cd backend && uv run python ../test/cleanup_e2e.py
```

## Conventions

- `e2e/fixtures.ts` seeds the `avatar_conversation` cookie to a known UUID, seeds
  the persisted theme, logs into admin, and records every conversation id to
  `test/screenshots/.e2e-conversations.txt` for the Python teardown.
- Admin specs read `ADMIN_PASSWORD` / `OWNER_NAME` from the repo `.env`
  (loaded in `playwright.config.ts`); they `skip` if the password is absent.
- `workers: 1` (serial) for deterministic screenshots and no Supabase contention.

---

## 1. Visitor — `e2e/visitor.spec.ts`
- [x] Intro hero renders in **dark**; owner name personalized from `/api/config`; 3 suggestion chips; composer autofocused; page title carries the owner name. (screenshot)
- [x] Intro hero renders in **light** (`data-theme=light`). (screenshot)
- [x] Theme toggle flips dark↔light and persists to `localStorage`.
- [x] Instant `Qn` answer with **no LLM call**: avatar bubble shows `instant · Q1` tag and restates the question; composer regains focus. (screenshot)
- [x] Streaming chat returns a grounded answer; the intro hero hides once the thread has content. (screenshot)
- [x] Suggestion chip submits its prompt immediately (optimistic visitor bubble).
- [x] Deep link `/?q=1` answers on arrival and strips `?q=` from the URL. (screenshot)
- [x] Keep-chat restores the thread from Supabase on reload.
- [x] Reset clears the thread and restores the intro hero.
- [x] Rate limit (429) shows the friendly "too quickly" banner (route mocked).

## 2. Admin — `e2e/admin.spec.ts`
- [x] Login gate renders (dark + light); password field autofocused; dashboard hidden. (screenshots)
- [x] Wrong password shows an error and stays gated.
- [x] Correct password opens the dashboard; owner chip shows the owner's first name. (screenshot)
- [x] Inbox lists a seeded conversation (searchable) and opens its thread (marks read); visitor + avatar bubbles render. (screenshot)
- [x] Owner posts a human message (Enter sends); it renders as `You · sent to visitor`. (screenshot)
- [x] Logout returns to the gate.
- [x] **Mobile master/detail**: tapping a conversation flips to the thread (`.show-detail`); back control returns to the inbox. (screenshot)

## 3. Three-way + multi-user — `e2e/three-way.spec.ts` (desktop)
- [x] Visitor asks an instant question; owner opens the **same** thread in admin and posts a live reply; the visitor's page surfaces the human bubble **via the 10s poll**, labelled `{OWNER_NAME} · live` per SPEC #4/#11. (screenshots: visitor + admin)
- [x] Two visitors with **independent** `conversation_id`s keep separate threads (neither sees the other's message); the admin inbox shows both.

## Defects found & fixed during E2E
- [x] **Admin login gate covered the dashboard after sign-in.** `.login-gate { display:flex }` and `.dashboard { display:grid }` overrode the `[hidden]` attribute the admin JS toggles, so the fixed-position gate (z-index 50) kept intercepting clicks. Fixed with a global `[hidden] { display:none !important }` in `admin.css` (standard normalize pattern). Caught only because the E2E hit-tests real clicks.
- [x] **Admin composer copy was inaccurate.** It read "the visitor sees this … with no name shown," but the visitor bubble is labelled `{owner} · live` (SPEC #4). Corrected to "labelled live."

## Results
- [x] 35 tests pass across desktop + mobile (3 skipped by viewport/desktop guards).
- [x] 23 screenshots captured under `test/screenshots/`.
- [x] Screenshots deleted and E2E Supabase conversations removed (done at end of all testing).
