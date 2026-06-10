# Docker End-to-End Test Plan

Verifies the SPEC success criterion: build the single container with the provided
script, run the whole application from that container, and exercise it
end-to-end with the visitor, the Avatar, and the human all participating (and
multiple visitors with distinct `conversation_id`s).

## Build & run (the SPEC-mandated path)

```
./scripts/start_pc.ps1        # Windows: stop old container, docker build, docker run -p 8000:8000 --env-file .env
# (./scripts/start_mac.sh on macOS)
```

The container is the multi-stage `Dockerfile`: stage 1 builds the Vite frontend
(`node:24-alpine`), stage 2 installs the backend with `uv` (`python:3.12-slim`),
copies the built static assets + `knowledge/`, and runs `uvicorn`.

## Build verification
- [x] `docker build` succeeds from a clean context (image `avatar:latest`).
- [x] Frontend builds inside the container: `tsc --noEmit` passes, `vite build` emits `dist/`.
- [x] Backend deps install via `uv sync --frozen --no-install-project --no-dev` (81 packages).
- [x] Knowledge + built static assets copied to `/app/knowledge` and `/app/static`.
- [x] Container starts and binds `0.0.0.0:8000` (mapped to `localhost:8000`).

## Runtime smoke
- [x] `GET /healthz` → 200 within ~1s of start.
- [x] `GET /api/config` → `{"owner_name":"Quinten Kocian"}` (owner name from env, not hardcoded).
- [x] `GET /` serves the production visitor document (`<title>Avatar — Digital Twin</title>`).
- [x] `GET /admin` serves the admin document.
- [x] Container logs are clean across the full run: **no** error / warning / traceback lines; `/api/chat` returns 200.

## Full E2E against the container (Playwright, baseURL = container :8000)
The complete Playwright suite (see `frontend-test-plan.md`) was re-run against the
running container — **identical pass result**, proving the shipped artifact behaves
like the dev build.

- [x] Visitor: intro (dark/light), instant `Qn`, **streaming chat via the real model**, deep link, keep-chat restore, reset, rate-limit banner — desktop + mobile.
- [x] Admin: auth gate + wrong/right password, inbox list + search, open thread (mark read), **owner posts a human message**, logout, mobile master/detail.
- [x] **Three-way**: visitor asks → owner replies live from admin → visitor receives the human bubble via the 10s poll, labelled `Quinten Kocian · live`.
- [x] **Multiple visitors**: two independent `conversation_id`s stay isolated; admin inbox shows both.
- [x] 35 tests pass (3 skipped by viewport/desktop guards), both desktop and mobile projects.

## Result
- [x] The single Docker container builds via the script and runs the whole app end-to-end.
- [x] Visitor + Avatar + human three-way verified live against the container, with screenshots.
- [x] Multiple concurrent visitor conversations verified.
- [x] Stop with `./scripts/stop_pc.ps1` (`stop_mac.sh` on macOS).

## Post-test cleanup
- [x] All test conversations deleted from Supabase (E2E-tracked ids + any strays).
- [x] Screenshots deleted from `test/screenshots/`.
