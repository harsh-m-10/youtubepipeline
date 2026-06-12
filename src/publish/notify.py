"""Telegram notifications: 'video ready, tap to publish' on success,
stage + error on failure. Never raises — notification failure must not
fail the pipeline."""

import logging

import requests

from src import config

log = logging.getLogger(__name__)


def send(text: str) -> None:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        log.warning("Telegram not configured; message was: %s", text)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=20,
        ).raise_for_status()
    except Exception as exc:
        log.warning("Telegram send failed: %s", exc)


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
