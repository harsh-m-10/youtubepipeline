"""Background footage from Pexels (portrait, keyword-matched per beat) and
Pillow-rendered brand cards (opening topic card, closing "what do you think" card).
Fallback chain: Pexels keyword -> generic queries -> plain gradient card."""

import logging
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from src import config

log = logging.getLogger(__name__)

PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
FALLBACK_QUERIES = ["abstract background", "city timelapse", "data visualization"]

BG_TOP = (22, 28, 48)  # dark navy gradient — channel brand
BG_BOTTOM = (10, 12, 22)
ACCENT = (255, 210, 77)
RED = (235, 87, 87)
GREEN = (86, 196, 137)
MUTED = (150, 160, 185)


def _font(size: int, weight: str = "ExtraBold") -> ImageFont.FreeTypeFont:
    fonts_dir = config.ASSETS_DIR / "fonts"
    if fonts_dir.exists():
        ttfs = list(fonts_dir.glob("*.ttf"))
        preferred = [f for f in ttfs if weight.lower() in f.stem.lower()]
        if preferred or ttfs:
            return ImageFont.truetype(str((preferred or ttfs)[0]), size)
    return ImageFont.load_default(size)


def _gradient_canvas() -> Image.Image:
    """Vertical navy gradient with a subtle accent glow top-left."""
    col = Image.new("RGB", (1, config.VIDEO_H))
    for y in range(config.VIDEO_H):
        t = y / config.VIDEO_H
        col.putpixel((0, y), tuple(
            int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)
        ))
    img = col.resize((config.VIDEO_W, config.VIDEO_H))
    draw = ImageDraw.Draw(img, "RGBA")
    draw.ellipse([-400, -400, 700, 700], fill=(*ACCENT, 14))
    return img


def _badge(draw: ImageDraw.ImageDraw, cx: int, y: int) -> None:
    """Channel name pill."""
    font = _font(44, "SemiBold")
    text = "RABBIT HOLE DAILY"
    w = draw.textlength(text, font=font)
    pad_x, pad_y = 44, 24
    box = [cx - w / 2 - pad_x, y - pad_y - 22, cx + w / 2 + pad_x, y + pad_y + 22]
    draw.rounded_rectangle(box, radius=46, outline=ACCENT, width=4)
    draw.text((cx, y), text, font=font, fill=ACCENT, anchor="mm")


def _draw_spiral(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: float,
                 turns: float = 3.5, color=ACCENT, width: int = 9) -> None:
    """Archimedean spiral narrowing to a dark center — the brand 'rabbit hole'."""
    import math

    pts = []
    steps = int(turns * 60)
    for i in range(steps + 1):
        frac = i / steps
        ang = turns * 2 * math.pi * frac
        rad = r * (1 - frac)  # spiral inward
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    draw.line(pts, fill=color, width=width, joint="curve")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_title_card(belief: str, out_dir: Path) -> Path:
    img = _gradient_canvas()
    draw = ImageDraw.Draw(img)
    cx = config.VIDEO_W // 2

    # keep everything above y~1350: the lower third belongs to burned captions
    _badge(draw, cx, 300)
    eyebrow = _font(46, "SemiBold")
    draw.text((cx, 470), "D I D   Y O U   K N O W ?",
              font=eyebrow, fill=MUTED, anchor="mm")
    draw.line([(cx - 70, 540), (cx + 70, 540)], fill=ACCENT, width=6)

    main_font = _font(88)
    lines = _wrap(draw, belief, main_font, config.VIDEO_W - 180)
    if len(lines) > 5:  # very long claims get a smaller face
        main_font = _font(70)
        lines = _wrap(draw, belief, main_font, config.VIDEO_W - 180)
    line_h = int(main_font.size * 1.3)
    y = 880 - (len(lines) - 1) * line_h // 2
    for line in lines:
        draw.text((cx, y), line, font=main_font, fill="white", anchor="mm")
        y += line_h

    draw.text((cx, min(y + 110, 1290)), "weird true things you didn't know",
              font=_font(44, "SemiBold"), fill=ACCENT, anchor="mm")

    path = out_dir / "title_card.png"
    img.save(path)
    return path


def make_question_card(out_dir: Path) -> Path:
    """Closing card: invite the viewer to share what they think (no verdict)."""
    img = _gradient_canvas()
    draw = ImageDraw.Draw(img)
    cx = config.VIDEO_W // 2

    # keep everything above y~1350: the lower third belongs to burned captions
    _badge(draw, cx, 300)
    _draw_spiral(draw, cx, 640, r=190, turns=3.5)

    draw.text((cx, 940), "WHAT DO", font=_font(96), fill="white", anchor="mm")
    draw.text((cx, 1050), "YOU THINK?", font=_font(120), fill=ACCENT, anchor="mm")

    draw.rounded_rectangle([cx - 430, 1180, cx + 430, 1290], radius=55, fill=ACCENT)
    draw.text((cx, 1235), "TELL ME IN THE COMMENTS",
              font=_font(48), fill=(12, 14, 24), anchor="mm")

    path = out_dir / "question_card.png"
    img.save(path)
    return path


def _pexels_search(query: str) -> str | None:
    """Return the best portrait video file URL for a query, or None."""
    try:
        resp = requests.get(
            PEXELS_VIDEO_API,
            headers={"Authorization": config.PEXELS_API_KEY},
            params={"query": query, "orientation": "portrait", "per_page": 3},
            timeout=20,
        )
        resp.raise_for_status()
        for video in resp.json().get("videos", []):
            files = sorted(
                (f for f in video["video_files"] if f.get("height")),
                key=lambda f: abs(f["height"] - config.VIDEO_H),
            )
            if files:
                return files[0]["link"]
    except Exception as exc:
        log.warning("Pexels search failed for %r: %s", query, exc)
    return None


def fetch_clips(keywords: list[str], out_dir: Path) -> list[Path | None]:
    """One clip per beat keyword. None entries fall back to the title card image."""
    clips: list[Path | None] = []
    for i, kw in enumerate(keywords):
        url = _pexels_search(kw)
        if url is None:
            for fb in FALLBACK_QUERIES:
                url = _pexels_search(fb)
                if url:
                    break
        if url is None:
            log.warning("No clip for %r, will use static card", kw)
            clips.append(None)
            continue
        path = out_dir / f"clip_{i}.mp4"
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        clips.append(path)
        log.info("Clip %d (%s): downloaded", i, kw)
    return clips
