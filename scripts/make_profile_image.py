"""Generate channel profile image variants for "Rabbit Hole Daily"
(YouTube avatar, 800x800, shown as a circle — all content stays inside the
safe circle). The mark is a descending spiral / vortex "rabbit hole".

Usage: python scripts/make_profile_image.py
Outputs out/brand/profile_v*.png
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from src.media.visuals import _font, ACCENT, BG_TOP, BG_BOTTOM

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


def spiral(draw: ImageDraw.ImageDraw, cy: int, r: float, turns: float = 4.0,
           width: int = 16, color=ACCENT) -> None:
    """Archimedean spiral narrowing to a dark center — the 'rabbit hole'."""
    pts, steps = [], int(turns * 80)
    for i in range(steps + 1):
        frac = i / steps
        ang = turns * 2 * math.pi * frac
        rad = r * (1 - frac)
        pts.append((CX + rad * math.cos(ang), cy + rad * math.sin(ang)))
    # taper: draw with a soft dark core dot at the center
    draw.line(pts, fill=color, width=width, joint="curve")
    draw.ellipse([CX - 18, cy - 18, CX + 18, cy + 18], fill=BG_BOTTOM)


def v1_minimal(out: Path) -> None:
    """Spiral + double ring, nothing else — cleanest at avatar size."""
    img = radial_canvas()
    draw = ImageDraw.Draw(img)
    ring(draw, 16, 10, ACCENT)
    ring(draw, 44, 3, (70, 80, 110))
    spiral(draw, CY, r=250, turns=4.0, width=18)
    img.save(out / "profile_v1_minimal.png")


def v2_spiral_glow(out: Path) -> None:
    """Spiral with a fading multi-tone vortex for more depth."""
    img = radial_canvas()
    draw = ImageDraw.Draw(img)
    ring(draw, 16, 10, ACCENT)
    spiral(draw, CY, r=270, turns=4.5, width=22, color=(255, 224, 130))
    spiral(draw, CY, r=250, turns=4.5, width=10, color=ACCENT)
    img.save(out / "profile_v2_spiral_glow.png")


def v3_wordmark(out: Path) -> None:
    """Spiral up top with the channel name stacked below."""
    img = radial_canvas()
    draw = ImageDraw.Draw(img)
    ring(draw, 16, 10, ACCENT)
    spiral(draw, CY - 120, r=170, turns=4.0, width=14)
    draw.text((CX, 560), "RABBIT HOLE", font=_font(60), fill="white", anchor="mm")
    draw.text((CX, 632), "DAILY", font=_font(80), fill=ACCENT, anchor="mm")
    img.save(out / "profile_v3_wordmark.png")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "out" / "brand"
    out.mkdir(parents=True, exist_ok=True)
    v1_minimal(out)
    v2_spiral_glow(out)
    v3_wordmark(out)
    print(f"3 variants written to {out}")
