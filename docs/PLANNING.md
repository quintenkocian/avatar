# Avatar — Planning: Scaling Issues & Proposed Alternatives

This document captures issues surfaced during a design review of the current
implementation, together with proposed alternative solutions, their architectural
impact, and an effort estimate (t‑shirt size). It is a **planning / discussion**
artifact — not an authoritative contract. `SPEC.md` still wins on behaviour and
`docs/ARCHITECTURE.md` records the as‑built design.

**Effort scale:** XXS · XS · S · M · L · XL · XXL (relative implementation +
testing effort, not calendar time).

**Important framing:** today the app is **single‑tenant** (one owner — Quinten —
and that owner's visitors). Most items below are not problems at that scale. They
are recorded because (a) some are cheap latency/quality wins now, and (b) the
multi‑tenant direction (§7) multiplies the load and turns several single‑process
shortcuts into real architectural limits.

---

## Table of contents

1. [Session & connection model (context, not a defect)](#1-session--connection-model)
2. [Polling latency after idle backoff](#2-polling-latency-after-idle-backoff)
3. [Push instead of poll for the human's messages](#3-push-instead-of-poll)
4. [Single‑process in‑memory state vs. horizontal scaling](#4-single-process-in-memory-state)
5. [Agent memory model & unbounded transcript growth](#5-agent-memory--unbounded-transcript)
6. [The inbox full‑table scan](#6-the-inbox-full-table-scan)
7. [Multi‑tenancy (career agents for many owners)](#7-multi-tenancy)
8. [Prioritized roadmap](#8-prioritized-roadmap)

---

## 1. Session & connection model

**Status: context, not a defect.** Documented so the rest of the doc has a shared
mental model.

- The backend is **stateless HTTP**. There are no server‑side sessions and no
  long‑lived connections to "time out from inactivity."
- **Admin session:** a signed, timestamped cookie (`avatar_admin`), `MAX_AGE = 7
  days` (`backend/app/security.py`). Persistent cookie → survives browser restarts
  up to 7 days; verified on every `/admin/*` request. Nothing to expire on idle.
- **Visitor "Keep chat":** the `avatar_conversation` cookie holds the
  `conversation_id` UUID for ~365 days (`frontend/src/visitor/main.ts`). State lives
  in Supabase; the cookie is just the pointer. Closing/reopening the browser
  re‑reads the cookie and reloads the thread.
- **The only open connection** is the SSE stream during a single avatar reply
  (`POST /api/chat`). Between messages there is no standing connection; the client
  fires short polls instead.
- **Caveat:** in a cross‑site `<iframe>`, the `SameSite=Lax` cookie is treated as
  third‑party and may not persist — serve from a subdomain (Fly custom domain) to
  keep it first‑party (already noted in `DEPLOY.md`).

No change proposed. **Effort: —**

---

## 2. Polling latency after idle backoff

**Issue.** The visitor polls for the human's async messages every 10s, easing to
60s after 5 quiet minutes (`POLL_FAST_MS`/`POLL_SLOW_MS`/`POLL_SLOWDOWN_AFTER_MS`
in `frontend/src/visitor/main.ts`). So if a visitor has been idle ≥5 min and the
owner then replies from admin, the reply can take **up to ~60s** to appear (the
next slow‑cadence tick). It self‑corrects: once a human row arrives, `noteActivity()`
snaps back to the 10s cadence, so follow‑ups are fast.

This only bites the specific case of a fully passive visitor receiving an
unsolicited owner message. The 10s/60s scheme is mandated by `SPEC.md`, so changing
it is a deliberate deviation.

### Alternatives

| Option | Architecture impact | Effort |
|---|---|---|
| **2a. Tune the constants** (raise `POLL_SLOW_MS` toward fast, extend `POLL_SLOWDOWN_AFTER_MS`, or always poll 10s) | None structural; one‑line constant changes. Trade‑off: more idle requests against the backend. Deviates from SPEC's 10s/60s. | **XXS** |
| **2b. Push instead of poll** | See §3 — removes the latency entirely rather than tuning it. | see §3 |

**Recommendation:** if latency matters, prefer §3 (push) over tuning; tuning trades
latency for steady‑state load and still leaves a window.

---

## 3. Push instead of poll

**Goal.** Deliver the owner's admin reply to the visitor immediately, instead of on
the next poll tick. The key realization: this is **not a new architecture** — the
app already streams the avatar's reply over SSE (`StreamingResponse` +
`text/event-stream` in `backend/app/main.py`; `ReadableStream` parser in
`frontend/src/api.ts`). Pushing admin replies reuses that machinery; the only
differences are how long the connection stays open and what feeds it.

### Alternatives

**3a. Long‑lived SSE + in‑process pub/sub (recommended).**
The visitor opens a standing `GET /api/conversation/stream`. When the owner posts
(`adminPostMessage`), the handler publishes the row to an in‑memory registry keyed
by `conversation_id`; the matching SSE generator emits it.

- *Architecture impact:* new streaming endpoint + per‑conversation `asyncio.Queue`
  registry (~50–100 lines backend); a few lines in the admin‑post route to publish;
  frontend swaps the poll loop for `EventSource` (native, since it's a GET) with
  reconnect. The existing dedupe/watermark logic (`renderedIds`, `lastSeenId`,
  `renderRow`) is reused as‑is. **Single‑process only** (see §4): the in‑memory
  registry breaks across machines. Must handle disconnect cleanup to avoid queue
  leaks.
- *Effort:* **M**

**3b. Supabase Realtime.**
The browser subscribes directly to Postgres INSERTs over Supabase's websocket,
bypassing the backend for delivery.

- *Architecture impact:* **bigger**, not smaller. Today the browser never talks to
  Supabase — the backend holds the service key and security is "possession of
  `conversation_id` = access, enforced server‑side." Realtime means exposing the
  anon key to the browser + Row‑Level Security so a visitor only subscribes to its
  own thread. New auth surface + new frontend dependency. But it scales across
  machines natively (no in‑memory broker).
- *Effort:* **L**

**3c. Hybrid: push + keep a slow poll as fallback (recommended pairing with 3a).**
Add push, but retain a 60s safety poll. SSE drops, proxy idle timeouts, and
sleeping tabs are real; the slow poll guarantees correctness and degrades to
today's behaviour if the stream fails.

- *Architecture impact:* 3a plus leaving the existing poll in place at slow cadence.
- *Effort:* **M** (marginal over 3a)

**Recommendation:** 3a + 3c while single‑machine. If/when going multi‑machine,
either move the broker to Redis/Postgres `LISTEN`/`NOTIFY` (see §4) or adopt 3b.

---

## 4. Single‑process in‑memory state

**Issue.** Several pieces of state live in process memory and are correct **only on
a single machine/process**:

- the rate limiter (`backend/app/rate_limit.py`, `MemoryStorage`),
- any in‑process pub/sub introduced for push (§3a).

These work today because the reference deploy runs **one always‑on Fly machine**
(and `SPEC.md` explicitly accepts in‑memory state for the limiter). The moment the
app scales horizontally, in‑memory state fragments: a rate‑limit count or a push
event on machine 1 is invisible to machine 2. Note this is a **delivery / counting**
failure, not a concurrency race — within one async process, many connections are
cheap and lock‑free (single event loop).

### Alternatives

| Option | Architecture impact | Effort |
|---|---|---|
| **4a. Stay single‑machine (status quo)** | None. Document the ceiling. Valid until traffic or multi‑tenancy forces scale‑out. | **XXS** (doc only) |
| **4b. Shared rate‑limit store (Redis)** | `limits` already supports a Redis storage backend — swap `MemoryStorage` for it. Adds a Redis dependency/instance. Enables horizontal scale for limiting. | **S** |
| **4c. Shared pub/sub for push** — Postgres `LISTEN`/`NOTIFY` | Reuses the Supabase Postgres you already run: admin POST does `NOTIFY`, each machine's SSE loop `LISTEN`s. No new infra; keeps Supabase server‑side. | **M** |
| **4d. Shared pub/sub for push** — Redis pub/sub | Conventional broker if you outgrow `LISTEN`/`NOTIFY`. New Redis dependency. | **M** |

**Recommendation:** 4a now. When scaling out, 4b for limiting and 4c for push
(no new infra). Treat "are we going multi‑machine?" as the trigger.

---

## 5. Agent memory & unbounded transcript

**How memory works today.** The agent (`Runner.run_streamed`) is **stateless per
turn** — it receives one self‑contained task string and remembers nothing between
calls.

- **Long‑term memory** = the knowledge corpus (`knowledge.md`, `style.md`,
  `faq.jsonl`), loaded **once at import** into module globals
  (`KNOWLEDGE_MD`/`STYLE_MD`/`FAQS` in `backend/app/knowledge.py`) and baked into the
  system prompt. Static, shared by all conversations, in‑process cached.
- **Short‑term memory** = the conversation transcript in Supabase, fetched fresh
  each turn (`db.get_conversation`) and rendered into one labelled task
  (`build_user_task`). The database *is* the short‑term memory (hence it survives
  browser restarts). Nothing is cached; replies are generated fresh.

**Issue.** There is **no context window or summarization** — the *entire* transcript
is re‑sent to the LLM every turn. Token cost and the full‑thread fetch grow linearly
with conversation length. Fine for typical chats; a concern for very long ones.

### Alternatives

| Option | Architecture impact | Effort |
|---|---|---|
| **5a. Do nothing** | None. Acceptable for typical chat lengths. | **—** |
| **5b. Sliding window** (send last N turns) | Small change in `build_user_task` to cap rows. Risk: loses early context. | **XS** |
| **5c. Rolling summary** (summarize older turns into a running synopsis, keep recent verbatim) | New summarization step + a stored summary per conversation (extra column or table). Adds an LLM call when the thread crosses a threshold. | **M** |
| **5d. Prompt caching** (provider‑side cache of the static system prompt) | The large static prefix (knowledge corpus) is identical every turn; OpenRouter/provider prompt caching can cut input‑token cost. App‑side: keep the static prefix stable and contiguous. No structural change. | **S** |

**Recommendation:** 5a until conversations get long; then 5d (cheap token win) and
5b/5c as needed.

---

## 6. The inbox full‑table scan

**Issue (the one with real scaling teeth).** `list_conversations`
(`backend/app/db.py`) selects **every row in the `messages` table** and groups in
Python on each admin inbox load. Cost is O(all messages ever), independent of
concurrency, and grows forever. Single‑tenant it's merely wasteful; multi‑tenant
(§7) it scans every other owner's data too — a perf cliff *and* an isolation hole.

### Alternatives

| Option | Architecture impact | Effort |
|---|---|---|
| **6a. SQL aggregate / view** (compute per‑conversation summary, last message, unread/attention counts in the DB; return only the inbox rows) | Replace the full select + Python grouping with a Postgres view or RPC. Add indexes to support it. No schema change to `messages`. Big win. | **S** |
| **6b. Denormalized `conversations` summary table** (maintain one row per conversation: last_role/content/at, counts, flags, updated on insert) | New table + write‑path maintenance (trigger or app‑side on each insert/open/resolve). Inbox becomes a trivial indexed read. More moving parts; best at high volume. | **M** |
| **6c. Pagination + recency cutoff** (only most‑recent conversations, lazy‑load older) | Frontend + query change. Complements 6a/6b; doesn't fix the underlying scan alone. | **S** |

**Recommendation:** 6a first (largest win for least change). 6b if/when volume
justifies it, especially under multi‑tenancy.

---

## 7. Multi‑tenancy

**The scenario.** Expose the ability for others to create their own career agent.
If `m` owners each attract `n` concurrent visitors (mutually exclusive at a given
instant), concurrent load becomes **`m·n` visitors + `m` admins**. This is where the
single‑tenant shortcuts stop being acceptable.

**Key framing:** `m·n` is not inherently unscalable — a cleanly stateless app
absorbs it by adding machines. The real obstacle is the set of **single‑process /
single‑tenant assumptions** that block clean horizontal scaling. And the **first
wall is cost, not the DB**: `m·n ×` turn‑rate LLM calls hits OpenRouter throughput
and spend long before Postgres notices.

### What breaks, ranked

1. **No tenant key + the inbox scan (correctness/security first).** `messages` has
   `conversation_id` but **no `owner_id`**. Multi‑tenancy requires an owner
   dimension on every row + **Row‑Level Security** so no owner can read another's
   threads. And §6's full‑table scan now spans all tenants — both slow and a data
   leak.
2. **LLM key & cost model (a design fork to decide early).** Per‑owner OpenRouter
   keys (cost attribution + per‑tenant rate‑limit isolation) vs. a shared key (you
   eat the bill; one owner's traffic can starve another).
3. **In‑memory rate limiter (§4).** Per‑process; `m·n` forces scale‑out which breaks
   it. Needs a shared store, and should be keyed per‑tenant.
4. **Single‑owner knowledge globals (§5).** `KNOWLEDGE_MD`/`FAQS` are loaded once at
   import for one owner. Multi‑tenant needs per‑owner prompts — loaded/cached per
   owner, not as process globals; owner config (name, knowledge, keys) becomes
   first‑class data, not env vars.

### Alternatives

| Option | Architecture impact | Effort |
|---|---|---|
| **7a. Add tenant dimension + RLS** | New `owner_id` (or `owners` table) FK on `messages`; RLS policies; every query filtered by owner; admin auth scoped to an owner. Foundational — everything else depends on it. | **L** |
| **7b. Per‑owner config as data** | Move `OWNER_NAME`, knowledge corpus, model choice, and (optionally) API keys out of env/globals into per‑owner storage; load/cache per request or per owner. Replaces import‑time globals with an owner‑scoped cache. | **L** |
| **7c. Per‑owner LLM keys & quotas** | Store each owner's OpenRouter key; per‑tenant rate limits and spend caps. Isolation + cost attribution. | **M** |
| **7d. Shared rate‑limit / pub‑sub state** | §4b/4c, now mandatory rather than optional, and tenant‑keyed. | **M–L** |
| **7e. Full SaaS multi‑tenant migration** (7a–7d + onboarding/signup, billing, per‑owner asset pipeline incl. avatar image generation per `design-system/docs/avatar-generation.md`) | A product, not a patch. Touches schema, auth, config, infra, frontend, and ops. | **XXL** |

**Recommendation / order:** tenant isolation (7a) → inbox query (§6a) → LLM key &
cost model (7c) → shared rate‑limit state (7d) → per‑owner config (7b) →
onboarding/billing (rest of 7e). Isolation is the non‑negotiable first step
(correctness + security); everything else builds on it.

---

## 8. Prioritized roadmap

Ordered by value‑for‑effort, independent of the multi‑tenant decision unless noted.

| # | Change | Why now | Effort |
|---|---|---|---|
| 1 | §6a inbox SQL aggregate/view | Only piece with unbounded cost *today*; biggest win per change | **S** |
| 2 | §2a tune poll constants *or* §3a+3c push | Removes/limits the up‑to‑60s human‑reply latency | **XXS** / **M** |
| 3 | §5d provider prompt caching | Cheap token‑cost win as conversations lengthen | **S** |
| 4 | §4b Redis rate‑limit store | Prerequisite for any horizontal scale | **S** |
| 5 | §5b/5c transcript window/summary | When conversations get long | **XS–M** |
| **Multi‑tenant track (only if exposing to other owners)** | | | |
| 6 | §7a tenant key + RLS | Foundational; security + isolation | **L** |
| 7 | §7c per‑owner LLM keys & quotas | Cost attribution + isolation | **M** |
| 8 | §7b per‑owner config as data | Removes single‑owner globals | **L** |
| 9 | §7e onboarding/billing/asset pipeline | Turns it into a product | **XXL** |

### Cross‑cutting notes

- **The LLM is the first bottleneck**, not the database. At any real concurrency,
  OpenRouter throughput and spend bind before Postgres query load does. Optimize the
  call/cost model before micro‑optimizing queries.
- **Chat and polling load are the same order of magnitude** (~10–25 q/s per 100
  active visitors at realistic turn rates); neither is the thing to optimize first.
  Both are dwarfed by §6 (unbounded scan) and the LLM ceiling.
- **Push (§3) and shared state (§4)** are coupled: adding push while planning to
  scale out means choosing a cross‑machine broker (`LISTEN`/`NOTIFY` or Redis) up
  front.
