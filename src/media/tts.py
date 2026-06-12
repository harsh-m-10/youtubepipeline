"""Edge-TTS narration with word-level timestamps (WordBoundary events).
Timestamps drive the karaoke captions, so caption sync is exact by construction."""

import asyncio
import logging
from pathlib import Path

import edge_tts

from src import config

log = logging.getLogger(__name__)


async def _synthesize(text: str, mp3_path: Path) -> list[dict]:
    communicate = edge_tts.Communicate(
        text, config.TTS_VOICE, rate=config.TTS_RATE, boundary="WordBoundary"
    )
    words: list[dict] = []
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append(
                    {
                        "word": chunk["text"],
                        # offsets are in 100-nanosecond units
                        "start": chunk["offset"] / 1e7,
                        "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                    }
                )
    return words


def narrate(beats: list[dict], out_dir: Path) -> tuple[Path, list[dict], list[float]]:
    """Synthesize all beats as one narration. Returns (mp3 path, word timings,
    per-beat end times) — beat boundaries are used to switch background clips."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = out_dir / "narration.mp3"

    # Join beats with sentence pause; track word counts to find beat boundaries.
    full_text = " ".join(b["text"].strip() for b in beats)
    words = asyncio.run(_synthesize(full_text, mp3_path))
    if not words:
        raise RuntimeError("TTS produced no word boundaries")

    # Map each beat to its end time by cumulative word count.
    beat_ends: list[float] = []
    idx = 0
    for b in beats:
        n = len(b["text"].split())
        idx = min(idx + n, len(words))
        beat_ends.append(words[idx - 1]["end"])
    beat_ends[-1] = words[-1]["end"]

    log.info("Narration: %.1fs, %d words", words[-1]["end"], len(words))
    return mp3_path, words, beat_ends
