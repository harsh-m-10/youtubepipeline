"""Instagram Reels publishing via the official Instagram Graph API
(graph.instagram.com, "Instagram API with Instagram Login" — no Facebook Page).

Publishing a Reel needs a publicly-reachable video URL. Since the repo is
public, we attach the MP4 to a temporary GitHub Release, hand Instagram that
asset URL, then delete the release once publishing finishes.

Long-lived tokens last 60 days and are refreshable; refresh_token() bumps it
and (if GH_PAT is set) pushes the new value back into the IG_ACCESS_TOKEN
secret so CI never goes stale. All failures are non-fatal to the caller —
Instagram is a fail-soft cross-post, never allowed to break the YouTube path."""

import logging
import subprocess
import time

import requests

from src import config

log = logging.getLogger(__name__)

GRAPH = "https://graph.instagram.com"


def _gh_release_url(video_path, tag: str) -> str:
    """Upload the MP4 as a GitHub release asset; return its public download URL."""
    env_token = config.GH_PAT
    import os

    env = {**os.environ, "GH_TOKEN": env_token} if env_token else dict(os.environ)
    gh = "gh"
    subprocess.run(
        [gh, "release", "create", tag, str(video_path),
         "-R", config.GH_REPO, "-t", tag, "-n", "temp asset for IG publish"],
        check=True, capture_output=True, text=True, env=env,
    )
    # Public repo asset URL pattern
    fname = video_path.name
    return f"https://github.com/{config.GH_REPO}/releases/download/{tag}/{fname}"


def _gh_release_delete(tag: str) -> None:
    import os

    env = {**os.environ, "GH_TOKEN": config.GH_PAT} if config.GH_PAT else dict(os.environ)
    subprocess.run(
        ["gh", "release", "delete", tag, "-R", config.GH_REPO, "--yes", "--cleanup-tag"],
        capture_output=True, text=True, env=env,
    )


def upload_reel(video_path, caption: str) -> str | None:
    """Publish a Reel. Returns the IG media id, or None on failure (fail-soft)."""
    if not (config.IG_USER_ID and config.IG_ACCESS_TOKEN):
        log.warning("Instagram not configured; skipping cross-post")
        return None

    tag = f"ig-{int(time.time())}"
    try:
        video_url = _gh_release_url(video_path, tag)
        log.info("IG: temp asset at %s", video_url)

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
    finally:
        _gh_release_delete(tag)


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
            import os

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
