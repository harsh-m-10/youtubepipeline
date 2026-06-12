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

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _service():
    creds = Credentials(
        token=None,
        refresh_token=config.YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.YT_CLIENT_ID,
        client_secret=config.YT_CLIENT_SECRET,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


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
