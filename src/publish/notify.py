"""WhatsApp notifications via CallMeBot (free personal-use gateway):
'video ready, tap to publish' on success, stage + error on failure.
Never raises — notification failure must not fail the pipeline.

One-time setup (see README): add CallMeBot's number to your contacts,
WhatsApp it "I allow callmebot to send me messages", and it replies
with your API key."""

import logging

import requests

from src import config

log = logging.getLogger(__name__)


def send(text: str) -> None:
    if not (config.WHATSAPP_PHONE and config.CALLMEBOT_API_KEY):
        log.warning("WhatsApp not configured; message was: %s", text)
        return
    try:
        requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={
                "phone": config.WHATSAPP_PHONE,
                "text": text,
                "apikey": config.CALLMEBOT_API_KEY,
            },
            timeout=30,
        ).raise_for_status()
    except Exception as exc:
        log.warning("WhatsApp send failed: %s", exc)


def video_ready(title: str, video_id: str) -> None:
    send(
        f"🎬 Video ready (private): {title}\n\n"
        f"Review & publish: https://studio.youtube.com/video/{video_id}/edit\n"
        f"Watch: https://youtu.be/{video_id}"
    )


def pipeline_failed(stage: str, error: str) -> None:
    send(f"❌ Pipeline failed at stage '{stage}':\n{error[:500]}")


def no_video_today(best_score: float) -> None:
    send(f"😴 No video today — best hypothesis scored {best_score:.1f}, below the bar.")
