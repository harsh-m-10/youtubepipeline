"""Background footage from Pexels (portrait, keyword-matched per beat) and
Pillow-rendered brand cards (opening hypothesis card, closing vote card).
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
    text = "NULL HYPOTHESIS"
    w = draw.textlength(text, font=font)
    pad_x, pad_y = 44, 24
    box = [cx - w / 2 - pad_x, y - pad_y - 22, cx + w / 2 + pad_x, y + pad_y + 22]
    draw.rounded_rectangle(box, radius=46, outline=ACCENT, width=4)
    draw.text((cx, y), text, font=font, fill=ACCENT, anchor="mm")


def _draw_check(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GREEN, width=8)
    draw.line([(cx - r * 0.45, cy + r * 0.02), (cx - r * 0.12, cy + r * 0.38),
               (cx + r * 0.5, cy - r * 0.32)], fill=GREEN, width=14, joint="curve")


def _draw_cross(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RED, width=8)
    k = r * 0.42
    draw.line([(cx - k, cy - k), (cx + k, cy + k)], fill=RED, width=14)
    draw.line([(cx - k, cy + k), (cx + k, cy - k)], fill=RED, width=14)


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
    draw.text((cx, 470), "T H E   H Y P O T H E S I S",
              font=eyebrow, fill=MUTED, anchor="mm")
    draw.line([(cx - 70, 540), (cx + 70, 540)], fill=ACCENT, width=6)

    main_font = _font(88)
    lines = _wrap(draw, belief, main_font, config.VIDEO_W - 180)
    if len(lines) > 5:  # very long beliefs get a smaller face
        main_font = _font(70)
        lines = _wrap(draw, belief, main_font, config.VIDEO_W - 180)
    line_h = int(main_font.size * 1.3)
    y = 880 - (len(lines) - 1) * line_h // 2
    for line in lines:
        draw.text((cx, y), line, font=main_font, fill="white", anchor="mm")
        y += line_h

    draw.text((cx, min(y + 110, 1290)), "both sides. real evidence. you decide.",
              font=_font(44, "SemiBold"), fill=ACCENT, anchor="mm")

    path = out_dir / "title_card.png"
    img.save(path)
    return path


def make_question_card(out_dir: Path) -> Path:
    """Closing card: the channel never rules — the viewer votes in the comments."""
    img = _gradient_canvas()
    draw = ImageDraw.Draw(img)
    cx = config.VIDEO_W // 2

    # keep everything above y~1350: the lower third belongs to burned captions
    _badge(draw, cx, 300)
    draw.text((cx, 540), "DOES THE NULL HYPOTHESIS",
              font=_font(60), fill="white", anchor="mm")
    draw.text((cx, 690), "SURVIVE?", font=_font(160), fill=ACCENT, anchor="mm")

    # two vote options with drawn icons (no unicode glyph dependence)
    opt_font = _font(52)
    left, right, icon_y, r = cx - 250, cx + 250, 960, 70
    _draw_check(draw, left, icon_y, r)
    draw.text((left, icon_y + r + 65), "SURVIVES", font=opt_font, fill=GREEN, anchor="mm")
    _draw_cross(draw, right, icon_y, r)
    draw.text((right, icon_y + r + 65), "REJECTED", font=opt_font, fill=RED, anchor="mm")

    draw.rounded_rectangle([cx - 410, 1210, cx + 410, 1320], radius=55, fill=ACCENT)
    draw.text((cx, 1265), "VOTE IN THE COMMENTS",
              font=_font(50), fill=(12, 14, 24), anchor="mm")

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
