# SKILL — Building the Avatar UI from this design system

> This is the **design + front-end build brief** for the Avatar platform. It tells you
> (Claude Code) how to turn this design system into the real product UI.
>
> **Source of truth split:**
> - `SPEC.md` (project root) governs *what the product does* and the *backend* — Agents SDK,
>   OpenRouter, Supabase schema, auth, streaming/polling, tools. Defer to it for all behaviour.
> - **This folder** (`avatar-design-system/`) governs *how the product looks and feels* — tokens,
>   components, icons, the avatar identity, the two screens, and the interaction details that
>   make the UI correct. Defer to it for all visual/UX decisions.
>
> When the two ever seem to disagree, SPEC.md wins on behaviour, this system wins on appearance.

---

## 0. The one-paragraph brief

Avatar is a personal **digital-twin** web app. A visitor chats with an AI twin of the site's
owner. The owner can silently join from `/admin` and post as themselves — a **three-way
conversation** (visitor · avatar · human). The design language is **sharp, fresh, editorial and
unmistakably not a generic chatbot**: a characterful serif for display, a crisp grotesque for UI,
monospace for the technical layer, a navy-tinted dark-first surface, **blue-led** accents with
**yellow as the spark** reserved for the human-in-the-loop, and **purple locked to primary
actions only**. No gradients in chrome, no purple wash, no left-edge accent bars, no emoji.

---

## 1. What's in this folder

```
avatar-design-system/
├─ Avatar Design System.html   ← the navigable system doc (read this rendered first)
├─ tokens.css                  ← ALL design tokens (dark + light). Single source of truth.
├─ components.css              ← build-ready component classes (depends on tokens.css)
├─ icons.svg                   ← icon sprite — <use href="icons.svg#i-…">
├─ doc.css                     ← styles for the doc page only (NOT product code)
├─ assets/
│   ├─ avatar-human.png        ← the owner's real photo, square crop
│   ├─ avatar-robot.png        ← synthetic twin, square + HUD frame
│   └─ avatar-robot-round.png  ← synthetic twin, tuned for circular chat avatars
├─ mockups/
│   ├─ Visitor Chat.html       ← reference hi-fi screen (dark/light toggle)
│   └─ Admin Dashboard.html    ← reference hi-fi screen (dark/light toggle)
└─ docs/
    ├─ ux-flows.md             ← every interaction contract in detail
    ├─ components.md           ← component-by-component spec & class reference
    └─ avatar-generation.md    ← how the twin image is produced (regenerate per owner)
```

**Do this first:** open `Avatar Design System.html` in a browser and read it top to bottom. The
two mockups are the literal target for the visitor and admin screens.

---

## 2. How to use the system in the real frontend

The frontend is **vanilla TypeScript + Vite** (per SPEC, no framework). Wiring the design in:

1. **Copy `tokens.css`, `components.css`, `icons.svg` and `assets/` into the frontend** (e.g.
   `frontend/src/styles/` and `frontend/public/`). These are framework-agnostic plain CSS/SVG.
2. **Load order:** `tokens.css` → `components.css` → your page CSS. Import the Google Fonts used:
   `Newsreader`, `Hanken Grotesk`, `JetBrains Mono` (weights as in the mockup `<head>`).
3. **Theme** is set with `data-theme="dark"` or `"light"` on `<html>`. Default **dark**. Persist
   the choice (the mockups use `localStorage['avatar-theme']`). Honour `prefers-color-scheme` on
   first visit if you like, but dark is the hero.
4. **Icons:** `<svg class="icon"><use href="/icons.svg#i-send"/></svg>`. They inherit
   `currentColor`. Sizes: `.icon` 20, `.icon--sm` 16, `.icon--lg` 24.
5. **Build screens by composing the component classes** in `components.css` — they already cover
   buttons, fields, the Keep-chat switch, badges, avatars, the three message bubbles, tool-status,
   the composer and the inbox rows. The mockups show the exact markup; lift it.
6. **Do not invent new colours.** If you need a tone the tokens don't have, derive it in OKLCH at
   the same chroma/lightness as the nearest brand hue, and add it to `tokens.css` for *both* themes.

---

## 3. Screen 1 — Visitor chat  (served at `/`)

Target: `mockups/Visitor Chat.html`. Key requirements (cross-check SPEC §"Interactive Chat"):

- **Top bar:** brand (mark + "Avatar" + owner subtitle) · a name/initials field · a **Keep chat**
  switch (defaults **on**) · **Reset** · theme toggle.
- **Keep chat on** → read `conversation_id` from cookie; if present, fetch and restore the thread.
  **Reset** clears the view and issues a fresh `conversation_id`.
- **Conversation column** centred, `max-width: var(--container-chat)` (760px). Messages use
  `.msg--visitor / .msg--avatar / .msg--human` exactly as in §4.
- **Composer** (`.composer`) docked at the bottom. **It must take focus on load and regain focus
  after every send** (click or Enter) — this is a hard SPEC requirement. `Enter` sends,
  `Shift+Enter` is a newline.
- **Qn instant answer:** if the trimmed message matches `^q\d{1,2}$` (e.g. `Q2`), skip the model,
  return the FAQ answer directly, and tag the reply `.instant-tag` ("instant · Q2").
- **Streaming:** the avatar reply streams over **SSE**. While streaming, render tool activity as
  `.tool-status` lines in small mono ("Calling faq_tool…" → done state). See `docs/ux-flows.md`.
- **Polling for the human:** poll every **10s**, easing to **60s** after 5 quiet minutes, to pick
  up async human messages. When one arrives, render it as the **human** bubble (§4).

## 4. The three roles (never confuse them)

| Role | Avatar | Align | Bubble class | Identity cues |
|------|--------|-------|--------------|----------------|
| **Visitor** | initials token (`.avatar-initials`) | right | `.msg--visitor` | blue token, neutral bubble, squared inner corner |
| **Avatar** | `avatar-robot-round.png` in `.avatar-twin` | left | `.msg--avatar` | name "Avatar", cyan ring, tool-status lines above bubble |
| **Human** | `avatar-human.png` in `.avatar-human` + spark badge | left | `.msg--human` | yellow ring, tinted+glowing bubble, name-free "live" tag |

**The human is anonymous by design.** The human bubble shows the photo + a **name-free** tag
(e.g. "The human · live"). **Never hardcode the owner's name in the human bubble** — students
reuse this platform. The distinction is carried by image + ring + tint + glow, not text.

## 5. Screen 2 — Admin dashboard  (served at `/admin`)

Target: `mockups/Admin Dashboard.html`. Cross-check SPEC §"Human Admin Experience".

- **Login gate first:** `/admin` shows a password screen (`.btn--primary` submit, `i-lock`,
  `i-shield` security note) → `POST /admin/login` with `ADMIN_PASSWORD` sets an httpOnly session
  cookie guarding all `/admin/*` APIs. (Build the gate even though the mockup shows the
  authed dashboard; a minimal centred card using these tokens is enough.)
- **Sidebar = inbox** (`.sidebar`, width `var(--sidebar-w)` 340px). Conversations **most-recent
  first**, each row `.convo-item`: initials avatar, name, timestamp, preview.
  - `.is-unread` → brighter text + blue dot (`.badge--dot`).
  - `.is-attention` (a `push_tool` fired → `needs_attention`) → yellow glow + "Needs you" badge,
    persists **until the owner opens the thread**.
  - `.is-active` → selected row.
- **Main panel:** thread header (initials, name, `conv_…` id in mono, started time, count, the
  "Avatar asked for you" flag + "Mark resolved"), the full thread, then the **admin composer**.
- **Posting as you:** the composer carries an explicit note — the visitor sees the message from the
  owner's **photo, with no name**, and **the Avatar does not react to it** (per SPEC Q&A #4).
- **Keyboard-first:** `↑`/`↓` move between conversations, `Enter` sends, `Shift+Enter` newline.
- **Read/unread + needs_attention** are row fields in Supabase (see SPEC + README schema); opening
  a thread clears unread and `needs_attention`.

---

## 6. The avatar identity

- `avatar-human.png` is the owner's real photo (square crop of `knowledge/pic.jpg`). Natural,
  never stylised. In the chat it gets a **yellow ring** (`.avatar-human`) when the human is live.
- `avatar-robot*.png` is the **synthetic twin**: the same face rebuilt as cool chrome (navy→cyan
  duotone, posterised paneling, scanlines, glowing eyes, HUD brackets). This is the **Avatar's**
  identity everywhere, ringed cyan-blue (`.avatar-twin`).
- **Regenerate per owner:** the twin is produced programmatically from `pic.jpg` — see
  `docs/avatar-generation.md` for the exact recipe so a different site owner gets a matching twin.

## 7. Brand mark

Two discs sharing an axis — one solid (human), one outlined with a yellow node (twin). Inline SVG,
provided in the mockups' `.brand-mark`. Geometric only; never redraw it as illustration.

---

## 8. Acceptance checklist (UI)

- [ ] Both screens match the mockups in **dark and light**; dark is default.
- [ ] All colour/space/type comes from `tokens.css`; no stray hex values in components.
- [ ] Visitor composer takes focus on load and after each send.
- [ ] `Qn` returns an instant answer, tagged, with no model call.
- [ ] Avatar replies stream with visible tool-status; composer re-focuses on completion.
- [ ] Human messages render as the human bubble — photo, ring, glow, **no name**.
- [ ] Admin inbox shows unread + needs-you states correctly; opening clears them.
- [ ] `↑/↓` navigate threads; `Enter`/`Shift+Enter` behave per spec.
- [ ] No gradients in chrome, no purple outside primary actions, no left-edge accent bars, no emoji.
- [ ] Icons come from `icons.svg`; no ad-hoc icon drawing.

## 9. Testing (per SPEC §Testing)

Use Playwright, capture screenshots of both screens in both themes and every state in §"States to
design for" (see `docs/ux-flows.md`). Verify the three-way flow end to end with the model set to
`gpt-5.4-nano`. Clean up test screenshots and test Supabase threads when done. Document and check
off the plans in `test/`.
