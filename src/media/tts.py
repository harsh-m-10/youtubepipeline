"""Edge-TTS narration with word-level timestamps (WordBoundary events).
Timestamps drive the karaoke captions, so caption sync is exact by construction."""

import asyncio
import logging
import subprocess
from pathlib import Path

import edge_tts

from src import config

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# Fastest plausible speaking rate at +15%: ~4 words/sec. A narration shorter
# than words/4 seconds means the edge-tts stream died mid-synthesis (the
# "15-second video that loses its voice" failure), not that the voice was quick.
MAX_WORDS_PER_SECOND = 4.0
# The mp3's real duration must roughly match the last word boundary; audio much
# shorter than the boundaries means the stream sent timings but dropped audio.
MAX_AUDIO_BOUNDARY_GAP = 1.5


def _audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


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
    n_words = len(full_text.split())
    min_duration = n_words / MAX_WORDS_PER_SECOND

    # edge-tts streams can die mid-synthesis (CI network flakes / endpoint
    # throttling), leaving a truncated mp3 that still "succeeds". Validate the
    # result against the script length and retry; fail closed rather than
    # shipping a video whose voice cuts out halfway.
    words: list[dict] = []
    problem = "no attempts made"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        words = asyncio.run(_synthesize(full_text, mp3_path))
        if not words:
            problem = "no word boundaries"
        elif words[-1]["end"] < min_duration:
            problem = (f"narration {words[-1]['end']:.1f}s is too short for "
                       f"{n_words} words (expected >={min_duration:.1f}s) - truncated stream")
        elif (gap := words[-1]["end"] - _audio_duration(mp3_path)) > MAX_AUDIO_BOUNDARY_GAP:
            problem = (f"audio is {gap:.1f}s shorter than the last word boundary "
                       f"({words[-1]['end']:.1f}s) - stream dropped audio chunks")
        else:
            break
        log.warning("TTS attempt %d invalid: %s", attempt, problem)
        words = []
    if not words:
        raise RuntimeError(f"TTS failed after {MAX_ATTEMPTS} attempts: {problem}")

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
