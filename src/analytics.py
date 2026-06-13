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
    # merge title for readability
    by_id = {h["video_id"]: h for h in history}
    merged = {
        vid: {**s, "title": by_id.get(vid, {}).get("title", "")}
        for vid, s in stats.items()
    }
    PERFORMANCE_FILE.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Refreshed stats for %d videos", len(merged))
    return merged


def _load() -> dict[str, dict]:
    if PERFORMANCE_FILE.exists():
        return json.loads(PERFORMANCE_FILE.read_text(encoding="utf-8"))
    return {}


def calibration_block(min_videos: int = 5) -> str:
    """A compact 'audience taste' summary for the scoring prompt. Empty until
    there are enough data points to be meaningful."""
    stats = _load()
    ranked = sorted(stats.values(), key=lambda s: s.get("views", 0), reverse=True)
    if len(ranked) < min_videos:
        return ""
    top = ranked[:5]
    bottom = ranked[-5:]
    lines = ["These earlier videos performed BEST (high views) — favor similar topics:"]
    lines += [f"  + {v['title']} ({v['views']} views)" for v in top if v["title"]]
    lines.append("These performed WORST — avoid similar topics:")
    lines += [f"  - {v['title']} ({v['views']} views)" for v in bottom if v["title"]]
    return "\n".join(lines)
