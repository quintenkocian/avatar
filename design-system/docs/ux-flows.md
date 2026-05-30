# UX Flows & Interaction Contracts

The parts of Avatar that don't show up in a screenshot. Pair with `SPEC.md` for backend behaviour.

---

## A. Visitor — first visit

1. Page loads → composer **autofocuses**. Editorial hero + 2–3 suggestion chips are visible above
   an empty thread.
2. Browser mints a `conversation_id` (UUID). With **Keep chat** on (default), it is written to a
   cookie so the thread survives refreshes.
3. Visitor sends a message → renders as `.msg--visitor` (initials token). Composer clears and
   **re-focuses**.

## B. Visitor — returning (Keep chat on)

1. On load, read `conversation_id` from cookie.
2. Call the backend for the existing thread; render all prior messages in order.
3. Resume polling (§E) and scroll to the latest message.

`Reset` clears the visible thread and issues a **new** `conversation_id` (old thread stays in the
DB, just detached from this browser).

## C. Avatar reply (streaming)

1. Visitor submits → optimistic visitor bubble appears.
2. Backend runs the Agent (OpenAI Agents SDK via OpenRouter) and **streams** the reply over SSE.
3. Tool activity renders live as `.tool-status` rows in small mono, e.g.
   `Calling faq_tool…` → on return collapse to the `.is-done` state `faq_tool · curriculum`.
4. Text streams token-by-token into the `.bubble`.
5. On completion the **composer re-focuses**. (Hard requirement.)

States to render: `thinking` · `tool-calling` · `tool-returned` · `typing` · `complete`.

## D. Qn instant answer (no model call)

- If `message.trim()` matches `^q\d{1,2}$` (case-insensitive), look the FAQ up by number and return
  its answer **directly** — no Agent run.
- Tag the reply `.instant-tag` → "instant · Q2". Still persist both the user line and the answer to
  the thread so history is complete.

## E. Polling for the human

- Poll the backend for new messages every **10 seconds**.
- After **5 minutes** with no new activity, ease the interval to **60 seconds**.
- Resume the fast 10s cadence as soon as the visitor sends again.
- New `human` messages arriving via poll render as `.msg--human` (§ roles) — the designed moment.

## F. Contact capture → human-in-the-loop

1. Visitor expresses intent to reach the owner (or the Avatar can't answer).
2. Avatar asks for an email, then calls `push_tool` (Pushover) to notify the human, and tells the
   visitor in-chat that it has done so.
3. That message row is flagged `needs_attention = true`, `read = false`.
4. In `/admin` the thread glows yellow + "Needs you" and sorts to attention.
5. Owner replies from admin → inserted as the **human** role. **The Avatar does not react to it.**
6. The visitor's polling surfaces the human bubble.

## G. Admin — triage loop

1. `/admin` → password gate (`POST /admin/login`, httpOnly session cookie).
2. Inbox lists conversations, most-recent first, with read / unread / needs-you states.
3. `↑` / `↓` move the selection between threads; selecting one loads the full conversation **and
   clears its unread + needs_attention flags**.
4. Owner types a reply; `Enter` sends, `Shift+Enter` adds a line. The "posting as you" note makes
   clear the visitor sees only the photo, no name.
5. "Mark resolved" clears the attention flag without replying.

---

## States matrix (design + test every cell)

| Surface | States |
|---|---|
| Conversation row | read · unread · needs-you · active · hover |
| Message | visitor · avatar · avatar+tool · avatar+instant(Qn) · human |
| Composer | empty(focused) · typing · sending · disabled |
| Stream | thinking · tool-calling · tool-returned · typing · complete |
| Session | fresh · restored-from-cookie · reset |
| Admin auth | logged-out (gate) · logging-in · error · logged-in |
