"""Generate the owner's avatar set from knowledge/pic.png.

Implements the recipe in design-system/docs/avatar-generation.md so any owner gets
a matching synthetic digital twin from their own photo. Produces three PNGs:

  avatar-human.png        natural square crop of the real photo (human icon)
  avatar-robot.png        the twin, square, with a HUD frame (hero/showcase)
  avatar-robot-round.png  the twin tuned for circular chat avatars (ring+vignette)

Run with ephemeral deps (no project deps touched):
  uv run --with opencv-python-headless --with numpy --with pillow \
      python scripts/generate_avatars.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "knowledge" / "pic.png"
# Pass a directory as argv[1] to preview there; otherwise write to the real homes.
if len(sys.argv) > 1:
    OUT_DIRS = [Path(sys.argv[1])]
else:
    OUT_DIRS = [REPO / "frontend" / "public", REPO / "design-system" / "assets"]
SIZE = 900  # output square edge

# Cool navy -> cyan duotone ramp (recipe step 1).
RAMP = [
    (0.00, "#04122a"),
    (0.20, "#0a2e4e"),
    (0.40, "#166896"),
    (0.60, "#2c96c4"),
    (0.80, "#7dcdec"),
    (1.00, "#e4f6ff"),
]


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def build_lut() -> np.ndarray:
    """256x3 RGB lookup table by linear interpolation across the ramp stops."""
    lut = np.zeros((256, 3), np.float32)
    stops = [(p, _hex(c)) for p, c in RAMP]
    for i in range(256):
        t = i / 255.0
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                f = 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
                lut[i] = np.array(c0) * (1 - f) + np.array(c1) * f
                break
        else:
            lut[i] = stops[-1][1]
    return lut


# --- Face detection + crop ---------------------------------------------------


def detect_face_eyes(bgr: np.ndarray):
    """Return (face_xywh, (eyeL, eyeR)) using Haar cascades, with fallbacks."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    base = cv2.data.haarcascades
    face_cc = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
    eye_cc = cv2.CascadeClassifier(base + "haarcascade_eye.xml")

    faces = face_cc.detectMultiScale(gray, 1.1, 5, minSize=(120, 120))
    if len(faces) == 0:
        h, w = gray.shape
        side = int(min(w, h) * 0.6)
        fx, fy = (w - side) // 2, int(h * 0.12)
        face = (fx, fy, side, side)
    else:
        face = tuple(max(faces, key=lambda f: f[2] * f[3]))

    fx, fy, fw, fh = face
    roi = gray[fy : fy + int(fh * 0.6), fx : fx + fw]
    eyes = eye_cc.detectMultiScale(roi, 1.1, 6, minSize=(30, 30))
    centers = sorted(
        [(fx + ex + ew / 2, fy + ey + eh / 2) for ex, ey, ew, eh in eyes],
        key=lambda c: c[0],
    )
    if len(centers) >= 2:
        eyeL, eyeR = centers[0], centers[-1]
    else:
        # Estimate eyes from the face box (eyes ~42% down, at 30% / 70% width).
        eyeL = (fx + 0.32 * fw, fy + 0.42 * fh)
        eyeR = (fx + 0.68 * fw, fy + 0.42 * fh)
    return face, (np.array(eyeL), np.array(eyeR))


def crop_square(rgb: np.ndarray):
    """Square crop centred on the face, eyes ~44% from top; resize to SIZE.

    Returns (crop_rgb, eyeL_xy, eyeR_xy) with eye coords in the SIZE space.
    """
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    (fx, fy, fw, fh), (eyeL, eyeR) = detect_face_eyes(bgr)
    h, w = rgb.shape[:2]

    eye_y = (eyeL[1] + eyeR[1]) / 2
    center_x = (eyeL[0] + eyeR[0]) / 2
    side = float(np.clip(fw * 2.05, 200, min(w, h)))
    top = eye_y - 0.44 * side
    left = center_x - side / 2

    # Keep the square inside the image.
    left = float(np.clip(left, 0, w - side))
    top = float(np.clip(top, 0, h - side))
    l, t, s = int(round(left)), int(round(top)), int(round(side))
    s = min(s, w - l, h - t)

    crop = rgb[t : t + s, l : l + s]
    crop = cv2.resize(crop, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    scale = SIZE / s
    eL = (np.array(eyeL) - [l, t]) * scale
    eR = (np.array(eyeR) - [l, t]) * scale
    return crop, eL, eR


# --- Twin treatment ----------------------------------------------------------


def figure_alpha(crop_rgb: np.ndarray) -> np.ndarray:
    """Alpha mask of the person against the studio background.

    A bright dress shirt is near-white just like a white studio backdrop, so it
    cannot be separated by colour/connectivity (the shirt merges with the
    background region). Instead we build the body silhouette geometrically:

      1. ``solid`` = the non-near-white parts (blazer, skin, hair, glasses).
      2. Union the *large* solid components — the collar splits the body into a
         head+neck piece and a shoulders piece, so we keep every sizable blob,
         not just the largest.
      3. Fill each row between the union's leftmost and rightmost solid pixel.
         This follows the real body outline and re-includes the shirt (it sits
         between the blazer edges) without dragging in the surrounding backdrop
         or leaving rectangular protrusions / neck wedges.
    """
    hsv = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    near_white = ((val > 200) & (sat < 45)).astype(np.uint8)
    h, w = near_white.shape

    solid = cv2.morphologyEx(
        (near_white == 0).astype(np.uint8),
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    )
    n, labels, stats, _ = cv2.connectedComponentsWithStats(solid)
    min_area = 0.012 * h * w
    body = np.zeros((h, w), np.uint8)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            body[labels == i] = 1

    alpha = np.zeros((h, w), np.uint8)
    for y in range(h):
        xs = np.where(body[y])[0]
        if xs.size:
            alpha[y, xs.min() : xs.max() + 1] = 255

    # Smooth the silhouette, then feather the boundary.
    alpha = cv2.morphologyEx(
        alpha, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    )
    alpha = cv2.GaussianBlur(alpha, (0, 0), 2.2)
    return alpha


def duotone(crop_rgb: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Smooth + posterise luminance, then map through the duotone LUT."""
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gray = cv2.GaussianBlur(gray, (0, 0), 2.0)  # kill speckle
    bands = 20
    gray = np.round(gray / 255.0 * (bands - 1)) / (bands - 1) * 255.0
    idx = np.clip(gray, 0, 255).astype(np.uint8)
    return lut[idx]  # HxWx3 float


def add_scanlines(rgb: np.ndarray) -> np.ndarray:
    out = rgb.copy()
    out[::3, :, :] *= 0.82
    return out


def add_paneling(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Faint cyan grid + diagonal accent lines, composited only on the figure."""
    h, w, _ = rgb.shape
    overlay = np.zeros((h, w, 3), np.float32)
    cyan = np.array(_hex("#7dcdec"), np.float32)
    step = 46
    for x in range(0, w, step):
        overlay[:, x : x + 1, :] = cyan
    for y in range(0, h, step):
        overlay[y : y + 1, :, :] = cyan
    # A couple of diagonal accent lines.
    diag = np.zeros((h, w), np.float32)
    for c in (-int(h * 0.15), int(w * 0.55)):
        for t in range(-2, 3):
            ys = np.arange(h)
            xs = ys + c + t
            ok = (xs >= 0) & (xs < w)
            diag[ys[ok], xs[ok]] = 1.0
    overlay[diag > 0] = cyan

    figure = (alpha.astype(np.float32) / 255.0)[:, :, None]
    return rgb * (1 - 0.10 * figure) + overlay * (0.10 * figure)


def add_eye_glow(rgb: np.ndarray, eyes) -> np.ndarray:
    """Subtle cyan eye glow.

    The glow is composited with a *screen* blend (not addition) so it reads as
    light without clipping the eye region to a flat, over-saturated white/cyan
    blob. The radii are kept tight (glow ~ just around each eye, not the whole
    lens) and the intensities are low.
    """
    h, w, _ = rgb.shape
    yy, xx = np.mgrid[0:h, 0:w]
    glow = np.zeros((h, w), np.float32)
    core = np.zeros((h, w), np.float32)
    rg = SIZE * 0.040  # tighter halo
    rc = SIZE * 0.009  # small bright pupil
    for ex, ey in eyes:
        d2 = (xx - ex) ** 2 + (yy - ey) ** 2
        glow += np.exp(-d2 / (2 * rg**2))
        core += np.exp(-d2 / (2 * rc**2))
    glow = np.clip(glow, 0, 1)
    core = np.clip(core, 0, 1)

    cyan = np.array(_hex("#8fd6f2"), np.float32)
    core_col = np.array(_hex("#d6f2ff"), np.float32)
    # Additive light layer, then screened so highlights roll off instead of
    # saturating. Low coefficients keep the eyes from blowing out.
    light = np.clip(
        cyan[None, None, :] * (glow[:, :, None] * 0.15)
        + core_col[None, None, :] * (core[:, :, None] * 0.22),
        0,
        255,
    )
    out = 255.0 - (255.0 - rgb) * (255.0 - light) / 255.0
    return np.clip(out, 0, 255)


def backdrop(round_variant: bool) -> np.ndarray:
    """Radial navy gradient with a faint grid (figure is composited on top)."""
    h = w = SIZE
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h * 0.46
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (SIZE * 0.72)
    r = np.clip(r, 0, 1)
    inner = np.array(_hex("#0b2240"), np.float32)
    outer = np.array(_hex("#04101f"), np.float32)
    bg = inner[None, None, :] * (1 - r[:, :, None]) + outer[None, None, :] * r[:, :, None]
    # Faint grid.
    grid = np.zeros((h, w), np.float32)
    for x in range(0, w, 60):
        grid[:, x] = 1
    for y in range(0, h, 60):
        grid[y, :] = 1
    bg += np.array(_hex("#13314f"), np.float32)[None, None, :] * grid[:, :, None] * 0.5
    if round_variant:
        bg *= (1 - 0.55 * (np.clip(r, 0, 1) ** 2))[:, :, None]  # vignette
    return np.clip(bg, 0, 255)


def composite(fig_rgb: np.ndarray, alpha: np.ndarray, round_variant: bool) -> np.ndarray:
    bg = backdrop(round_variant)
    a = (alpha.astype(np.float32) / 255.0)[:, :, None]
    return np.clip(fig_rgb * a + bg * (1 - a), 0, 255)


def draw_hud_square(arr: np.ndarray) -> np.ndarray:
    """Cyan corner brackets + one yellow tick."""
    img = Image.fromarray(arr.astype(np.uint8))
    d = ImageDraw.Draw(img)
    cyan = _hex("#5fd0f0")
    yellow = _hex("#ecad0a")
    m, ln, th = 46, 120, 6
    s = SIZE
    corners = [
        (m, m, 1, 1),
        (s - m, m, -1, 1),
        (m, s - m, 1, -1),
        (s - m, s - m, -1, -1),
    ]
    for x, y, sx, sy in corners:
        d.line([(x, y), (x + sx * ln, y)], fill=cyan, width=th)
        d.line([(x, y), (x, y + sy * ln)], fill=cyan, width=th)
    # One yellow tick on the top-left bracket.
    d.line([(m + 28, m), (m + 28, m + 26)], fill=yellow, width=th)
    return np.array(img)


def draw_ring_round(arr: np.ndarray) -> np.ndarray:
    """Inner cyan ring for the circular chat avatar."""
    img = Image.fromarray(arr.astype(np.uint8))
    d = ImageDraw.Draw(img)
    inset = 26
    d.ellipse(
        [inset, inset, SIZE - inset, SIZE - inset],
        outline=_hex("#5fd0f0"),
        width=5,
    )
    return np.array(img)


def save(arr: np.ndarray, alpha: np.ndarray | None, name: str) -> None:
    if alpha is None:
        img = Image.fromarray(arr.astype(np.uint8), "RGB")
    else:
        rgba = np.dstack([arr.astype(np.uint8), alpha.astype(np.uint8)])
        img = Image.fromarray(rgba, "RGBA")
    for d in OUT_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        img.save(d / name)
    print(f"wrote {name} ({img.size}, {img.mode}) -> {[str(d) for d in OUT_DIRS]}")


def main() -> int:
    if not SRC.exists():
        print(f"Source photo not found: {SRC}", file=sys.stderr)
        return 1
    rgb = np.array(Image.open(SRC).convert("RGB"))
    lut = build_lut()

    crop, eL, eR = crop_square(rgb)

    # 1) Human icon — natural crop.
    save(crop, None, "avatar-human.png")

    # 2) Twin — synthetic chrome.
    alpha = figure_alpha(crop)
    fig = duotone(crop, lut)
    fig = add_scanlines(fig)
    fig = add_paneling(fig, alpha)
    fig = add_eye_glow(fig, [eL, eR])

    square = composite(fig, alpha, round_variant=False)
    square = draw_hud_square(square)
    save(square, None, "avatar-robot.png")

    rnd = composite(fig, alpha, round_variant=True)
    rnd = draw_ring_round(rnd)
    save(rnd, None, "avatar-robot-round.png")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
