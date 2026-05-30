# Avatar generation recipe

The Avatar's icon is the owner's real photo (`knowledge/pic.jpg`) rebuilt as a **synthetic digital
twin**. It is produced programmatically so any site owner gets a matching twin from their own photo.
Three files are produced into `assets/`:

- `avatar-human.png` — natural square crop of the real photo (the **human** icon).
- `avatar-robot.png` — the twin, square, with a HUD frame (hero / showcase use).
- `avatar-robot-round.png` — the twin tuned for circular chat avatars (inner ring, vignette,
  no corner brackets).

## Crop
Square crop centred on the face. For `pic.jpg` (1500×1500): side ≈ 820px, centred at x≈750, with
the eyes at ≈44% from the top (`top = eyeY − 0.44·side`). Output at 900×900.

## Twin treatment (medium "synthetic chrome")
1. **Duotone** the cropped face through a cool navy→cyan ramp:
   `#04122a → #0a2e4e → #1668 96 → #2c96c4 → #7dcdec → #e4f6ff`.
2. **Smooth then posterise** luminance (small box-blur radius ~2 to kill JPEG speckle, then quantise
   to ~20 bands) for a paneled, rendered look.
3. **Remove the white background** with a border **flood-fill** on near-white / low-saturation
   pixels (a global threshold punches holes in bright skin — use flood-fill from the edges), feather
   the alpha at the boundary.
4. **Scanlines** — 1px darken every 3px. **Paneling seams** — a faint cyan grid + a couple of
   diagonal accent lines, composited `source-atop` so they only fall on the figure.
5. **Glowing eyes** — soft cyan radial glow + a bright core at each eye position.
6. **Backdrop** — radial navy gradient with a faint grid.
7. **HUD frame** (square variant) — cyan corner brackets + one yellow tick. **Round variant** —
   inner cyan ring + vignette instead of brackets.

The exact, working implementation used to produce the shipped assets is the canvas script in this
project's build history; the parameters above reproduce it. Tune ramp/levels to taste, but keep the
result **recognisably the person**, clearly **synthetic**, and **cool/blue** to read as the twin.

## Usage
- Human messages & admin owner chip → `avatar-human.png` in `.avatar-human` (yellow ring).
- Avatar messages → `avatar-robot-round.png` in `.avatar-twin` (cyan ring).
- Hero / identity showcase → `avatar-robot.png` (framed square).
