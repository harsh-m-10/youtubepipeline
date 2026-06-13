"""Instagram Reels publishing via the official Instagram Graph API
(graph.instagram.com, "Instagram API with Instagram Login" — no Facebook Page).

This API only accepts a publicly-reachable `video_url` (no direct byte upload),
so we stage the MP4 on litterbox (free, no account, auto-expires in a few hours)
which serves it with the video/mp4 content-type Instagram requires, hand IG that
URL, poll until processing finishes, then publish.

Long-lived tokens last 60 days and are refreshable; refresh_token() bumps it
and (if GH_PAT is set) pushes the new value back into the IG_ACCESS_TOKEN secret
so CI never goes stale. All failures are non-fatal to the caller — Instagram is
a fail-soft cross-post, never allowed to break the YouTube path."""

import logging
import os
import subprocess
import time

import requests

from src import config

log = logging.getLogger(__name__)

GRAPH = "https://graph.instagram.com"
LITTERBOX = "https://litterbox.catbox.moe/resources/internals/api.php"


def _stage_public_url(video_path) -> str:
    """Upload the MP4 to litterbox and return its direct, public video/mp4 URL.
    Auto-expires after 72h, so nothing needs cleaning up."""
    with open(video_path, "rb") as f:
        resp = requests.post(
            LITTERBOX,
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": ("reel.mp4", f, "video/mp4")},
            timeout=300,
        )
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"litterbox upload failed: {url[:200]}")
    return url


def upload_reel(video_path, caption: str) -> str | None:
    """Publish a Reel. Returns the IG media id, or None on failure (fail-soft)."""
    if not (config.IG_USER_ID and config.IG_ACCESS_TOKEN):
        log.warning("Instagram not configured; skipping cross-post")
        return None
    try:
        video_url = _stage_public_url(video_path)
        log.info("IG: staged video at %s", video_url)

        # 1. create media container
        r = requests.post(
            f"{GRAPH}/{config.IG_USER_ID}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption[:2200],
                "access_token": config.IG_ACCESS_TOKEN,
            },
            timeout=60,
        )
        r.raise_for_status()
        container_id = r.json()["id"]

        # 2. poll until Instagram finishes ingesting the video
        for _ in range(30):  # up to ~5 min
            time.sleep(10)
            s = requests.get(
                f"{GRAPH}/{container_id}",
                params={"fields": "status_code", "access_token": config.IG_ACCESS_TOKEN},
                timeout=30,
            ).json()
            code = s.get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                raise RuntimeError(f"IG container processing error: {s}")
            log.info("IG: container %s...", code)
        else:
            raise RuntimeError("IG container never reached FINISHED")

        # 3. publish
        p = requests.post(
            f"{GRAPH}/{config.IG_USER_ID}/media_publish",
            data={"creation_id": container_id, "access_token": config.IG_ACCESS_TOKEN},
            timeout=60,
        )
        p.raise_for_status()
        media_id = p.json()["id"]
        log.info("IG: published Reel media_id=%s", media_id)
        return media_id
    except Exception as exc:
        detail = getattr(exc, "response", None)
        log.warning("IG publish failed: %s %s", exc,
                    detail.text[:300] if detail is not None else "")
        return None


def refresh_token() -> None:
    """Refresh the 60-day long-lived token and push it back into the GitHub
    secret (needs GH_PAT). Safe to call every run; no-op if unconfigured."""
    if not config.IG_ACCESS_TOKEN:
        return
    try:
        r = requests.get(
            f"{GRAPH}/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": config.IG_ACCESS_TOKEN},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        new_token = data.get("access_token")
        expires_days = int(data.get("expires_in", 0)) // 86400
        if not new_token:
            return
        log.info("IG: token refreshed, valid ~%d more days", expires_days)
        if config.GH_PAT:
            env = {**os.environ, "GH_TOKEN": config.GH_PAT}
            proc = subprocess.run(
                ["gh", "secret", "set", "IG_ACCESS_TOKEN", "-R", config.GH_REPO],
                input=new_token, capture_output=True, text=True, env=env,
            )
            if proc.returncode == 0:
                log.info("IG: pushed refreshed token to GitHub secret")
            else:
                log.warning("IG: could not update secret: %s", proc.stderr[:200])
    except Exception as exc:
        log.warning("IG token refresh failed: %s", exc)
