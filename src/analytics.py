"""Performance feedback loop: pull view/like/comment counts for every
published video and persist them, so the hypothesis scorer can learn which
topics the audience actually watches.

Cheap: one YouTube Data API call per 50 videos, run at the start of each daily
run. Requires the force-ssl scope (already added for auto-comments)."""

import json
import logging

from src import config
from src.generate import hypothesis
from src.publish import youtube

log = logging.getLogger(__name__)

PERFORMANCE_FILE = config.STATE_FILE.parent / "performance.json"


def refresh_stats() -> dict[str, dict]:
    """Fetch current stats for all history video_ids, persist, and return them."""
    history = hypothesis.load_history()
    video_ids = [h["video_id"] for h in history if h.get("video_id")]
    if not video_ids:
        return {}
    try:
        stats = youtube.get_stats(video_ids)
    except Exception as exc:
        log.warning("Stats refresh failed: %s", exc)
        return _load()
    # merge title + publish date (for age-normalised views/day) for readability
    by_id = {h["video_id"]: h for h in history}
    merged = {
        vid: {
            **s,
            "title": by_id.get(vid, {}).get("title", ""),
            "date": by_id.get(vid, {}).get("date", ""),
        }
        for vid, s in stats.items()
    }
    # watch-time / retention (the real Shorts signal); no-op until the
    # yt-analytics.readonly scope is granted via a token re-auth.
    try:
        for vid, w in youtube.get_watchtime().items():
            if vid in merged:
                merged[vid].update(w)
        log.info("Merged watch-time for %d videos", len(merged))
    except Exception as exc:
        log.info("Watch-time unavailable (analytics scope not granted yet?): %s",
                 str(exc)[:160])
    PERFORMANCE_FILE.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Refreshed stats for %d videos", len(merged))
    return merged


def _load() -> dict[str, dict]:
    if PERFORMANCE_FILE.exists():
        return json.loads(PERFORMANCE_FILE.read_text(encoding="utf-8"))
    return {}


def _views_per_day(s: dict) -> float:
    """Age-normalised views: raw view counts just track how long a video has
    been up, so older videos always look 'better'. Dividing by days-since-publish
    is a fairer 'is this getting pushed?' signal when retention isn't available."""
    import datetime

    views = s.get("views", 0)
    date = s.get("date", "")
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat(date)).days
    except Exception:
        return float(views)
    return views / max(age, 1)


def calibration_block(min_videos: int = 5, min_views_for_retention: int = 15) -> str:
    """A compact 'audience taste' summary for the scoring prompt. Ranks by the
    best signal available: retention (avg_view_pct) > age-normalised views/day >
    raw views. Empty until there are enough data points to be meaningful.

    Retention % is volatile on tiny view counts (one looping viewer swings it),
    so it's only trusted for videos with at least `min_views_for_retention` views,
    and only when enough such videos exist; otherwise we fall back to views/day."""
    stats = list(_load().values())
    if len(stats) < min_videos:
        return ""

    retention_pool = [
        s for s in stats
        if "avg_view_pct" in s and s.get("views", 0) >= min_views_for_retention
    ]
    if len(retention_pool) >= min_videos:
        pool = retention_pool
        key = lambda s: s.get("avg_view_pct", 0.0)
        label = "% watched"
        fmt = lambda v: f"{v.get('avg_view_pct', 0):.0f}% watched"
    else:
        pool = stats
        key = _views_per_day
        label = "views/day"
        fmt = lambda v: f"{_views_per_day(v):.1f} views/day"

    ranked = sorted(pool, key=key, reverse=True)
    # disjoint halves: with a small pool, ranked[:5] and ranked[-5:] would overlap
    # and list the same video as both BEST and WORST (contradictory signal).
    k = min(5, len(ranked) // 2)
    top, bottom = ranked[:k], ranked[len(ranked) - k:]
    lines = [f"These earlier videos performed BEST by {label} — favor similar topics:"]
    lines += [f"  + {v['title']} ({fmt(v)})" for v in top if v.get("title")]
    lines.append("These performed WORST — avoid similar topics:")
    lines += [f"  - {v['title']} ({fmt(v)})" for v in bottom if v.get("title")]
    return "\n".join(lines)
