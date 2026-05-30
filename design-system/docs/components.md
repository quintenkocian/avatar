# Component Reference

Every class lives in `components.css` and is themed by `tokens.css`. Markup examples are lifted
from the mockups — copy them verbatim and swap content.

## Buttons — `.btn`
Modifiers: `--primary` (purple, **submit/primary only**), `--blue` (key secondary), `--secondary`
(outline), `--ghost` (quiet), `--icon`, `--sm`, `--lg`. Plus `.btn-send` (the 44px purple send
button). Focus ring is yellow.
```html
<button class="btn btn--primary"><svg class="icon icon--sm"><use href="#i-send"/></svg> Submit</button>
<button class="btn-send"><svg class="icon"><use href="#i-send"/></svg></button>
```

## Fields
`.input`, `.textarea`, `.name-field` (compact inline name/initials field), `.label`. Focus →
yellow ring (`--focus-ring`).

## Switch — `.switch` (Keep chat)
```html
<label class="switch">
  <input type="checkbox" checked>
  <span class="track"><span class="thumb"></span></span>
  <span class="switch-label">Keep chat</span>
</label>
```
On = blue track + blue thumb.

## Badges & status
`.badge` (+ `--attention` yellow, `--blue`, `--unread`, `--dot`, `.badge--dot.is-attention`),
`.chip`, `.kbd` (keyboard key), `.instant-tag` (Qn), `.tool-status` (+ `.is-done`).

## Avatars
- `.avatar` (+ `--sm` 30, `--lg` 56) — round image holder; set `background-image`.
- `.avatar-initials` — visitor's blue initials token (square, mono).
- `.avatar-twin` — cyan ring for the Avatar. Use `avatar-robot-round.png`.
- `.avatar-human` — yellow ring + `.spark-badge` for the live human. Use `avatar-human.png`.

## Message bubbles — `.msg`
Wrapper `.msg` + role modifier, containing the avatar element and `.msg-body`
(`.msg-meta` → `.msg-name` / `.msg-time` / tags, then `.bubble`).
- `.msg--visitor` — right aligned, initials token, neutral bubble.
- `.msg--avatar` — left, twin avatar, name "Avatar", `.tool-status` rows allowed above the bubble.
- `.msg--human` — left, human avatar, **name-free** `.human-tag` ("The human · live"), tinted +
  glowing bubble. No left-edge bar — the distinction is ring + tint + glow.

## Composer — `.composer`
Flex row: `<textarea>` + `.btn-send`. Auto-grows; focus-within → yellow ring. Always re-focus the
textarea after send.

## Inbox row — `.convo-item`
Grid: avatar / `.convo-main` (`.convo-top > .convo-name`, `.convo-preview`) / `.convo-side`
(time + badge). State classes: `.is-unread`, `.is-attention`, `.is-active`. Names truncate with
ellipsis; previews are single-line.

## Surfaces & utilities
`.card`, `.hairline`, `.eyebrow` (mono caps label), `.display` (serif), `.hud-grid` (decorative
technical grid background), `.scroll` (themed scrollbar).
