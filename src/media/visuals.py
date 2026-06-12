"""Background footage from Pexels (portrait, keyword-matched per beat) and
Pillow-rendered brand cards (opening belief card, closing verdict stamp).
Fallback chain: Pexels keyword -> generic queries -> plain gradient card."""

import logging
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from src import config

log = logging.getLogger(__name__)

PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
FALLBACK_QUERIES = ["abstract background", "city timelapse", "data visualization"]

BG_COLOR = (16, 20, 33)  # dark navy — channel brand
ACCENT = (255, 210, 77)
RED = (235, 87, 87)
GREEN = (76, 175, 125)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in sorted((config.ASSETS_DIR / "fonts").glob("*.ttf")) if (
        config.ASSETS_DIR / "fonts"
    ).exists() else []:
        return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size)


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
    img = Image.new("RGB", (config.VIDEO_W, config.VIDEO_H), BG_COLOR)
    draw = ImageDraw.Draw(img)
    eyebrow_font, main_font = _font(54), _font(88)

    draw.text((config.VIDEO_W // 2, 620), "EVERYONE BELIEVES",
              font=eyebrow_font, fill=ACCENT, anchor="mm")
    lines = _wrap(draw, f"“{belief}”", main_font, config.VIDEO_W - 160)
    y = 800
    for line in lines:
        draw.text((config.VIDEO_W // 2, y), line, font=main_font, fill="white", anchor="mm")
        y += 110
    draw.text((config.VIDEO_W // 2, y + 120), "— NULL HYPOTHESIS —",
              font=eyebrow_font, fill=(140, 150, 170), anchor="mm")

    path = out_dir / "title_card.png"
    img.save(path)
    return path


def make_verdict_card(verdict: str, out_dir: Path) -> Path:
    rejected = verdict == "REJECTED"
    img = Image.new("RGB", (config.VIDEO_W, config.VIDEO_H), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw.text((config.VIDEO_W // 2, 820), "NULL HYPOTHESIS",
              font=_font(72), fill="white", anchor="mm")
    draw.text((config.VIDEO_W // 2, 980), "REJECTED" if rejected else "SURVIVES",
              font=_font(140), fill=RED if rejected else GREEN, anchor="mm")
    draw.text((config.VIDEO_W // 2, 1160), "✗" if rejected else "✓",
              font=_font(120), fill=RED if rejected else GREEN, anchor="mm")

    path = out_dir / "verdict_card.png"
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
