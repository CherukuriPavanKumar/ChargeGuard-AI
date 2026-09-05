"""Render the Open Graph image and the apple-touch-icon.

MIRROR: this is the raster counterpart of
``frontend/src/components/ArbitrageFrontierStatic.jsx``. It plots the same
frontier from the same formula -- ``p* = lambda * c / A``, the one in
``lib/economics.js`` and ``sentinel/policy/economics.py`` -- over the same
deterministic scatter, so the social card and the hero fallback show the same
picture rather than two drawings that happen to look alike.

Run from ``frontend/``::

    python scripts/generate_og.py

Writes ``public/og.png`` (1200x630) and ``public/apple-touch-icon.png`` (180x180).

Regenerating is only necessary if the palette, the default cost, or the default
risk margin change. Both outputs are committed so a clean checkout has working
social previews without running this.
"""

from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# --- economics: identical to lib/economics.js -------------------------------
DEFAULT_COST_INR = 350.0
DEFAULT_RISK_MARGIN = 1.2
AMOUNT_MIN = 100.0
AMOUNT_MAX = 100_000.0


def decision_threshold(amount: float, cost: float, risk_margin: float) -> float:
    """p* = lambda * c / A. Unclamped, exactly as the authority defines it."""
    return (risk_margin * cost) / amount


# --- palette ----------------------------------------------------------------
OBSIDIAN = (10, 13, 20)
SURFACE = (13, 19, 32)
EMERALD = (16, 185, 129)
EMERALD_LIGHT = (52, 211, 153)
CORAL = (249, 115, 98)
SLATE = (148, 163, 184)
WHITE = (255, 255, 255)

W, H = 1200, 630
PAD_L, PAD_R, PAD_T, PAD_B = 90, 70, 200, 78

LOG_MIN = math.log(AMOUNT_MIN)
LOG_MAX = math.log(AMOUNT_MAX)

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"

FONT_DIRS = [
    "C:/Windows/Fonts",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/Library/Fonts",
    "/System/Library/Fonts",
]
FONT_CANDIDATES = {
    "bold": ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
             "LiberationSans-Bold.ttf", "verdanab.ttf"],
    "regular": ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
                "LiberationSans-Regular.ttf", "verdana.ttf"],
    "mono": ["consola.ttf", "cour.ttf", "DejaVuSansMono.ttf",
             "LiberationMono-Regular.ttf"],
}


def load_font(kind: str, size: int):
    """Load a face, falling back to Pillow's built-in bitmap font."""
    for name in FONT_CANDIDATES[kind]:
        for directory in FONT_DIRS:
            path = pathlib.Path(directory) / name
            if path.is_file():
                try:
                    return ImageFont.truetype(str(path), size)
                except OSError:
                    continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - Pillow < 10.1
        return ImageFont.load_default()


def mulberry32(seed: int):
    """Same PRNG family as the JSX, so the scatter is stable and comparable."""
    a = seed & 0xFFFFFFFF

    def rnd() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = (t ^ (t >> 15)) * (1 | t) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t ^= t
        t = a
        t = (t ^ (t >> 15)) * (1 | t) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t) & 0xFFFFFFFF)) ^ t
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return rnd


def sample_disputes(n: int, cost: float, lam: float, seed: int = 0x9E3779B9):
    """Lognormal amounts, centred probabilities, resolved against the frontier."""
    rnd = mulberry32(seed)
    out = []
    for _ in range(n):
        u1 = max(1e-9, rnd())
        u2 = rnd()
        z = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        amount = min(AMOUNT_MAX, max(AMOUNT_MIN, 2400 * math.exp(0.95 * z)))
        p = (rnd() + rnd() + rnd()) / 3.0
        thr = min(1.0, decision_threshold(amount, cost, lam))
        out.append((amount, p, p >= thr, abs(p - thr) < 0.05))
    return out


def px(amount: float) -> float:
    t = (math.log(amount) - LOG_MIN) / (LOG_MAX - LOG_MIN)
    return PAD_L + t * (W - PAD_L - PAD_R)


def py(p: float) -> float:
    return PAD_T + (1.0 - p) * (H - PAD_T - PAD_B)


def build_og(cost: float = DEFAULT_COST_INR, lam: float = DEFAULT_RISK_MARGIN) -> Image.Image:
    """Compose the 1200x630 card."""
    img = Image.new("RGB", (W, H), OBSIDIAN)

    # Very soft diagonal wash so the card is not a flat black rectangle.
    wash = Image.new("RGB", (W, H), OBSIDIAN)
    wd = ImageDraw.Draw(wash)
    for i in range(H):
        t = i / H
        wd.line(
            [(0, i), (W, i)],
            fill=(
                int(OBSIDIAN[0] + (SURFACE[0] - OBSIDIAN[0]) * t),
                int(OBSIDIAN[1] + (SURFACE[1] - OBSIDIAN[1]) * t),
                int(OBSIDIAN[2] + (SURFACE[2] - OBSIDIAN[2]) * t),
            ),
        )
    img = wash

    draw = ImageDraw.Draw(img, "RGBA")

    plot_top, plot_bottom = PAD_T, H - PAD_B
    plot_left, plot_right = PAD_L, W - PAD_R

    # Frontier sample points.
    curve = []
    for i in range(241):
        t = i / 240
        amount = math.exp(LOG_MIN + t * (LOG_MAX - LOG_MIN))
        thr = min(1.0, decision_threshold(amount, cost, lam))
        curve.append((px(amount), py(thr)))

    # Territory washes: CONTEST above the curve, ACCEPT below.
    above = curve + [(plot_right, plot_top), (plot_left, plot_top)]
    below = curve + [(plot_right, plot_bottom), (plot_left, plot_bottom)]
    draw.polygon(above, fill=(*EMERALD, 14))
    draw.polygon(below, fill=(*CORAL, 14))

    # Axis hairlines, no grid.
    draw.line([(plot_left, plot_top), (plot_left, plot_bottom)], fill=(*SLATE, 26), width=1)
    draw.line([(plot_left, plot_bottom), (plot_right, plot_bottom)], fill=(*SLATE, 26), width=1)

    mono_sm = load_font("mono", 15)
    for tick in (100, 1000, 10000, 100000):
        label = "₹1L" if tick >= 100000 else (f"₹{tick // 1000}k" if tick >= 1000 else f"₹{tick}")
        x = px(tick)
        draw.text((x, plot_bottom + 12), label, font=mono_sm, fill=(*SLATE, 110), anchor="ma")
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        draw.text((plot_left - 12, py(tick)), f"{tick:.2f}", font=mono_sm,
                  fill=(*SLATE, 110), anchor="rm")

    # Scatter, resolved.
    for amount, p, contest, near in sample_disputes(150, cost, lam):
        x, y = px(amount), py(p)
        r = 4.2 if near else 3.0
        alpha = 235 if near else 115
        colour = EMERALD if contest else CORAL
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(*colour, alpha))

    # Frontier: a blurred wide pass for bloom, then the crisp line on top.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).line(curve, fill=(*EMERALD, 150), width=16, joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(11))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    draw = ImageDraw.Draw(img, "RGBA")
    draw.line(curve, fill=EMERALD_LIGHT, width=5, joint="curve")

    # --- chrome: mark, wordmark, formula ---
    mark_x, mark_y, mark_s = PAD_L, 62, 58
    draw.rounded_rectangle(
        [mark_x, mark_y, mark_x + mark_s, mark_y + mark_s], radius=13, fill=(*SLATE, 16)
    )
    inner = []
    for i in range(29):
        t = i / 28
        gx = mark_x + mark_s * (0.20 + 0.66 * t)
        gy = mark_y + mark_s * (0.84 - 0.62 * (t ** 0.42))
        inner.append((gx, gy))
    draw.line(inner, fill=EMERALD, width=3, joint="curve")
    dot_x = mark_x + mark_s * 0.63
    dot_y = mark_y + mark_s * 0.30
    draw.ellipse([dot_x - 4.6, dot_y - 4.6, dot_x + 4.6, dot_y + 4.6], fill=EMERALD)

    f_word = load_font("bold", 50)
    f_sub = load_font("regular", 22)
    f_formula = load_font("mono", 27)

    tx = mark_x + mark_s + 22
    draw.text((tx, mark_y + 2), "ChargeGuard", font=f_word, fill=WHITE)
    ChargeGuard_w = draw.textlength("ChargeGuard", font=f_word)
    # Solid mid-grey, not white-with-alpha: text alpha is ignored when the
    # canvas is RGB, and the whole point is that ".AI" sits back from the name.
    draw.text((tx + ChargeGuard_w, mark_y + 2), ".AI", font=f_word, fill=(150, 158, 170))

    draw.text((tx, mark_y + 58), "Autonomous Chargeback Defense & Economic Arbitrage Engine",
              font=f_sub, fill=(*SLATE, 225))

    draw.text((W - PAD_R, mark_y + 14), "contest  if  p ≥ λc / A",
              font=f_formula, fill=EMERALD_LIGHT, anchor="ra")
    draw.text((W - PAD_R, mark_y + 50), "per dispute, not per portfolio",
              font=f_sub, fill=(*SLATE, 175), anchor="ra")

    # Axis captions.
    draw.text((plot_left, plot_top - 26), "calibrated win probability  p",
              font=mono_sm, fill=(*SLATE, 130))
    draw.text((plot_right, plot_bottom + 34), "dispute amount  A  (log)",
              font=mono_sm, fill=(*SLATE, 130), anchor="ra")

    return img


def build_icon(size: int = 180) -> Image.Image:
    """The mark alone, on the page background, for apple-touch-icon."""
    img = Image.new("RGB", (size, size), OBSIDIAN)
    draw = ImageDraw.Draw(img, "RGBA")

    pts = []
    for i in range(41):
        t = i / 40
        x = size * (0.19 + 0.66 * t)
        y = size * (0.84 - 0.63 * (t ** 0.42))
        pts.append((x, y))

    draw.line(
        [(size * 0.15, size * 0.87), (size * 0.55, size * 0.87)],
        fill=(*EMERALD, 90), width=max(2, size // 40),
    )
    draw.line(pts, fill=EMERALD, width=max(3, size // 22), joint="curve")

    r = size * 0.072
    cx, cy = size * 0.63, size * 0.31
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=EMERALD)
    return img


def main() -> int:
    PUBLIC.mkdir(parents=True, exist_ok=True)

    og = build_og()
    og_path = PUBLIC / "og.png"
    og.save(og_path, format="PNG", optimize=True)
    print(f"wrote {og_path.relative_to(ROOT)}  {og.size[0]}x{og.size[1]}  "
          f"{og_path.stat().st_size:,} B")

    icon = build_icon(180)
    icon_path = PUBLIC / "apple-touch-icon.png"
    icon.save(icon_path, format="PNG", optimize=True)
    print(f"wrote {icon_path.relative_to(ROOT)}  {icon.size[0]}x{icon.size[1]}  "
          f"{icon_path.stat().st_size:,} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
