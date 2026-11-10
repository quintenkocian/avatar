"""Generate the Open Graph social card (og-avatar.png, 1200x630) for the Avatar.

The card is what LinkedIn / Slack / etc. render when the Avatar link is shared.
It is derived from the brand palette (SPEC.md) and the synthetic twin avatar in
``frontend/public/avatar-robot.png``, and is owner-aware: the headline uses
``OWNER_NAME`` from ``.env``. It is written into ``frontend/public/`` so the
build bundles it and the app serves it at ``/og-avatar.png``; the visitor page
references it via ``og:image`` meta tags (see ``frontend/index.html`` and the
``serve_index`` handler, which rewrites the URL to absolute at request time).

Run with ephemeral deps (no project deps touched):

  uv run --with pillow python scripts/generate_og.py

Output: ``frontend/public/og-avatar.png`` (1200x630).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env", override=True)

OWNER = os.getenv("OWNER_NAME", "the owner").strip() or "the owner"
FIRST = OWNER.split()[0]

W, H = 1200, 630

# Brand palette (SPEC.md).
NAVY = (3, 33, 71)
NAVY_DEEP = (4, 18, 38)
BLUE = (32, 157, 215)
CYAN = (108, 211, 247)
YELLOW = (236, 173, 10)
INK = (233, 240, 250)
MUTED = (150, 173, 200)
GRID = (14, 42, 77)

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
SERIF_BOLD = FONT_DIR / "DejaVuSerif-Bold.ttf"
SANS = FONT_DIR / "DejaVuSans.ttf"
SANS_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    return mask


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def main() -> None:
    img = Image.new("RGB", (W, H), NAVY_DEEP)
    draw = ImageDraw.Draw(img)

    # Subtle HUD dot-grid texture (matches the visitor background), very low key.
    step = 46
    for y in range(40, H, step):
        for x in range(40, W, step):
            draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill=GRID)

    # A faint navy panel band behind the text for depth (no gradient).
    draw.rectangle([0, 0, W, H], outline=None)

    pad = 72
    # --- Brand lockup (top-left): two-circle mark + wordmark ---
    cx, cy = pad + 16, pad + 14
    draw.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], fill=BLUE)
    draw.ellipse([cx + 2, cy - 16, cx + 34, cy + 16], outline=BLUE, width=3)
    draw.ellipse([cx + 14, cy - 4, cx + 22, cy + 4], fill=YELLOW)
    draw.text((cx + 52, cy - 20), "Avatar", font=font(SANS_BOLD, 34), fill=INK)
    draw.text(
        (cx + 52, cy + 18),
        "DIGITAL TWIN",
        font=font(SANS_BOLD, 16),
        fill=MUTED,
    )

    # --- Right: the synthetic twin avatar in a rounded card with a cyan ring ---
    av_size = 348
    av_x = W - av_size - pad
    av_y = (H - av_size) // 2 + 18
    robot_path = REPO / "frontend" / "public" / "avatar-robot.png"
    if robot_path.exists():
        robot = Image.open(robot_path).convert("RGB").resize((av_size, av_size))
        radius = 36
        img.paste(robot, (av_x, av_y), rounded_mask(av_size, radius))
        # Ring + soft outer accent.
        draw.rounded_rectangle(
            [av_x, av_y, av_x + av_size, av_y + av_size],
            radius=radius,
            outline=CYAN,
            width=4,
        )
        draw.rounded_rectangle(
            [av_x - 8, av_y - 8, av_x + av_size + 8, av_y + av_size + 8],
            radius=radius + 8,
            outline=(20, 60, 96),
            width=2,
        )

    # --- Left: headline + subline + yellow accent bar ---
    text_x = pad
    text_w = av_x - pad - 56

    headline = f"{OWNER}'s digital twin"
    h_font = font(SERIF_BOLD, 70)
    h_lines = wrap(draw, headline, h_font, text_w)
    # Shrink to fit at most two lines.
    while len(h_lines) > 2 and h_font.size > 44:
        h_font = font(SERIF_BOLD, h_font.size - 4)
        h_lines = wrap(draw, headline, h_font, text_w)

    y = 250
    for line in h_lines:
        draw.text((text_x, y), line, font=h_font, fill=INK)
        y += int(h_font.size * 1.18)

    # Yellow accent bar.
    draw.rounded_rectangle([text_x, y + 6, text_x + 76, y + 12], radius=3, fill=YELLOW)

    sub = f"Ask me anything, and the real {FIRST} might just chime in."
    s_font = font(SANS, 28)
    s_lines = wrap(draw, sub, s_font, text_w)
    ys = y + 38
    for line in s_lines:
        draw.text((text_x, ys), line, font=s_font, fill=MUTED)
        ys += int(s_font.size * 1.35)

    out = REPO / "frontend" / "public" / "og-avatar.png"
    img.save(out, "PNG")
    print(f"Wrote {out} ({W}x{H})")


if __name__ == "__main__":
    main()
