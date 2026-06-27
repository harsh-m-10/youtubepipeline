"""YouTube upload via Data API v3 with a long-lived refresh token.
Uploads as PRIVATE (un-audited API projects are forced private anyway);
the human publishes with one tap in the YouTube app."""

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from src import config

log = logging.getLogger(__name__)

# force-ssl: post comments + read video status/statistics.
# yt-analytics.readonly: read watch time / retention (YouTube Analytics API).
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _credentials():
    # NOTE: do NOT pass scopes= here. On refresh, google-auth would request
    # exactly those scopes, and Google rejects the refresh (invalid_scope) if the
    # token wasn't granted all of them. Omitting scopes returns whatever the token
    # actually has — so adding yt-analytics.readonly to SCOPES (for the re-auth
    # script) can't break the live upload/stats path before re-auth happens.
    creds = Credentials(
        token=None,
        refresh_token=config.YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.YT_CLIENT_ID,
        client_secret=config.YT_CLIENT_SECRET,
    )
    creds.refresh(Request())
    return creds


def _service():
    return build("youtube", "v3", credentials=_credentials())


def upload(video_path: Path, title: str, description: str, tags: list[str]) -> str:
    """Resumable upload. Returns the video id."""
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags[:30],
            "categoryId": config.YT_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,  # AI-voice disclosure
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4",
                            chunksize=8 * 1024 * 1024, resumable=True)
    request = _service().videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("Upload %d%%", int(status.progress() * 100))
    video_id = response["id"]
    log.info("Uploaded video id=%s (private)", video_id)
    return video_id


def is_public(video_id: str) -> bool:
    """True if the video has been published (comments require a public video)."""
    resp = _service().videos().list(part="status", id=video_id).execute()
    items = resp.get("items", [])
    return bool(items) and items[0]["status"]["privacyStatus"] == "public"


def post_comment(video_id: str, text: str) -> None:
    """Post a top-level comment from the channel. Video must be public."""
    _service().commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": text}},
            }
        },
    ).execute()
    log.info("Posted engagement comment on %s", video_id)


def get_stats(video_ids: list[str]) -> dict[str, dict]:
    """Map video_id -> {views, likes, comments} for up to 50 ids per call."""
    stats: dict[str, dict] = {}
    svc = _service()
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        resp = svc.videos().list(part="statistics", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            s = item.get("statistics", {})
            stats[item["id"]] = {
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
            }
    return stats


def get_watchtime(start_date: str = "2026-06-01") -> dict[str, dict]:
    """Map video_id -> watch-time metrics via the YouTube Analytics API.
    Needs the yt-analytics.readonly scope; raises if the token lacks it (the
    caller treats that as "not available yet"). Retention is the real Shorts
    signal — avg_view_pct = % of the video the average viewer watched."""
    import datetime

    ya = build("youtubeAnalytics", "v2", credentials=_credentials())
    resp = ya.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=datetime.date.today().isoformat(),
        metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
        dimensions="video",
        sort="-estimatedMinutesWatched",  # the per-video report requires a sort
        maxResults=200,
    ).execute()
    out: dict[str, dict] = {}
    for row in resp.get("rows", []):
        vid, _views, minutes, avg_sec, avg_pct = row
        out[vid] = {
            "minutes_watched": round(float(minutes), 1),
            "avg_view_sec": round(float(avg_sec), 1),
            "avg_view_pct": round(float(avg_pct), 1),
        }
    return out
