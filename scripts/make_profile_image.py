"""Generate channel profile image variants (YouTube avatar, 800x800,
shown as a circle — all content stays inside the safe circle).

Usage: python scripts/make_profile_image.py
Outputs out/brand/profile_v*.png
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from src.media.visuals import _font, ACCENT, GREEN, RED, BG_TOP, BG_BOTTOM

SIZE = 800
CX = CY = SIZE // 2


def radial_canvas() -> Image.Image:
    """Radial navy gradient: lighter center, darker edge."""
    img = Image.new("RGB", (SIZE, SIZE))
    px = img.load()
    max_d = math.hypot(CX, CY)
    for y in range(SIZE):
        for x in range(SIZE):
            t = min(1.0, math.hypot(x - CX, y - CY) / max_d * 1.25)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM))
    return img


def ring(draw: ImageDraw.ImageDraw, margin: int, width: int, color) -> None:
    draw.ellipse([margin, margin, SIZE - margin, SIZE - margin],
                 outline=color, width=width)


def h_naught(draw: ImageDraw.ImageDraw, cy: int, scale: float = 1.0) -> None:
    """The H0 mark: big H in white, subscript 0 in accent yellow."""
    h_font = _font(int(360 * scale))
    o_font = _font(int(170 * scale))
    hw = draw.textlength("H", font=h_font)
    ow = draw.textlength("0", font=o_font)
    total = hw + ow + 10 * scale
    hx = CX - total / 2 + hw / 2
    draw.text((hx, cy), "H", font=h_font, fill="white", anchor="mm")
    draw.text((hx + hw / 2 + 10 * scale + ow / 2, cy + 120 * scale), "0",
              font=o_font, fill=ACCENT, anchor="mm")


def check(draw, cx, cy, r, width):
    draw.line([(cx - r, cy + r * 0.05), (cx - r * 0.25, cy + r * 0.8),
               (cx + r, cy - r * 0.7)], fill=GREEN, width=width, joint="curve")


def cross(draw, cx, cy, r, width):
    draw.line([(cx - r * 0.8, cy - r * 0.8), (cx + r * 0.8, cy + r * 0.8)],
              fill=RED, width=width)
    draw.line([(cx - r * 0.8, cy + r * 0.8), (cx + r * 0.8, cy - r * 0.8)],
              fill=RED, width=width)


def v1_minimal(out: Path) -> None:
    """H0 + double ring, nothing else."""
    img = radial_canvas()
    draw = ImageDraw.Draw(img)
    ring(draw, 16, 10, ACCENT)
    ring(draw, 44, 3, (70, 80, 110))
    h_naught(draw, CY - 10)
    img.save(out / "profile_v1_minimal.png")


def v2_verdict(out: Path) -> None:
    """H0 with small check/cross flanking below — the channel's question."""
    img = radial_canvas()
    draw = ImageDraw.Draw(img)
    ring(draw, 16, 10, ACCENT)
    h_naught(draw, CY - 70, scale=0.92)
    check(draw, CX - 150, 600, 52, 26)
    cross(draw, CX + 150, 600, 52, 26)
    draw.text((CX, 600), "or", font=_font(56, "SemiBold"), fill=(120, 130, 160),
              anchor="mm")
    img.save(out / "profile_v2_verdict.png")


def v3_wordmark(out: Path) -> None:
    """H0 with the channel name arced... simplified: name below."""
    img = radial_canvas()
    draw = ImageDraw.Draw(img)
    ring(draw, 16, 10, ACCENT)
    h_naught(draw, CY - 90, scale=0.85)
    draw.text((CX, 580), "NULL", font=_font(72), fill="white", anchor="mm")
    draw.text((CX, 660), "HYPOTHESIS", font=_font(54), fill=ACCENT, anchor="mm")
    img.save(out / "profile_v3_wordmark.png")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "out" / "brand"
    out.mkdir(parents=True, exist_ok=True)
    v1_minimal(out)
    v2_verdict(out)
    v3_wordmark(out)
    print(f"3 variants written to {out}")
