"""Pure-ffmpeg assembly (no MoviePy — fewer CI deps, faster).

Two-pass build:
  1. Normalize every segment (title card / beat clips / end card) to
     identical 1080x1920 30fps h264 chunks with exact durations.
  2. Concat, burn ASS captions, mix delayed narration + bed music, loudnorm.

ffmpeg is run with cwd=out_dir and relative filenames so Windows drive-letter
colons never need filtergraph escaping."""

import logging
import shutil
import subprocess
from pathlib import Path

from src import config

log = logging.getLogger(__name__)

FPS = 30
SEG_OPTS = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
    "-pix_fmt", "yuv420p", "-r", str(FPS), "-an",
]


def _run(args: list[str], cwd: Path) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def _image_segment(image: Path, duration: float, out_name: str, cwd: Path) -> str:
    _run(
        ["-loop", "1", "-i", image.name, "-t", f"{duration:.3f}",
         "-vf", f"scale={config.VIDEO_W}:{config.VIDEO_H}", *SEG_OPTS, out_name],
        cwd,
    )
    return out_name


def _clip_segment(clip: Path, duration: float, out_name: str, cwd: Path) -> str:
    vf = (
        f"scale={config.VIDEO_W}:{config.VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={config.VIDEO_W}:{config.VIDEO_H},eq=brightness=-0.18"
    )
    _run(
        ["-stream_loop", "-1", "-i", clip.name, "-t", f"{duration:.3f}",
         "-vf", vf, *SEG_OPTS, out_name],
        cwd,
    )
    return out_name


def assemble(
    out_dir: Path,
    title_card: Path,
    end_card: Path,
    clips: list[Path | None],
    beat_ends: list[float],
    narration: Path,
    ass_file: Path,
) -> Path:
    """Build final.mp4 in out_dir. The title card spans the first beat (the
    channel intro is narrated over it); `clips` cover the middle beats; the
    vote card spans the last beat plus a short hold. `beat_ends` is per-beat."""
    segments = [_image_segment(title_card, max(1.0, beat_ends[0]), "seg_title.mp4", out_dir)]
    prev = beat_ends[0]
    for i, clip in enumerate(clips):
        end = beat_ends[i + 1]
        dur = max(0.5, end - prev)
        prev = end
        name = f"seg_{i}.mp4"
        if clip is None:
            segments.append(_image_segment(title_card, dur, name, out_dir))
        else:
            segments.append(_clip_segment(clip, dur, name, out_dir))
    end_dur = max(0.5, beat_ends[-1] - prev) + config.END_CARD_HOLD_SECONDS
    segments.append(_image_segment(end_card, end_dur, "seg_end.mp4", out_dir))

    # 2. Concat
    concat_list = out_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{s}'\n" for s in segments), encoding="utf-8")
    _run(["-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "base.mp4"], out_dir)

    # 3. Captions + audio. Copy bundled fonts next to the ass file for libass.
    fonts_src = config.ASSETS_DIR / "fonts"
    if fonts_src.exists():
        shutil.copytree(fonts_src, out_dir / "fonts", dirs_exist_ok=True)

    total = beat_ends[-1] + config.END_CARD_HOLD_SECONDS

    music_files = sorted((config.ASSETS_DIR / "music").glob("*.mp3")) if (
        config.ASSETS_DIR / "music"
    ).exists() else []

    inputs = ["-i", "base.mp4", "-i", narration.name]
    if music_files:
        inputs += ["-stream_loop", "-1", "-i", str(music_files[0])]
        audio_filter = (
            f"[2:a]volume={config.MUSIC_VOLUME},afade=t=out:st={total - 2:.2f}:d=2[mus];"
            f"[1:a][mus]amix=inputs=2:duration=first:dropout_transition=0,"
            f"loudnorm=I=-16:TP=-1.5[aout]"
        )
    else:
        audio_filter = "[1:a]loudnorm=I=-16:TP=-1.5[aout]"

    _run(
        [*inputs,
         "-filter_complex",
         f"[0:v]ass={ass_file.name}:fontsdir=fonts[vout];{audio_filter}",
         "-map", "[vout]", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k",
         "-t", f"{total:.3f}", "final.mp4"],
        out_dir,
    )
    final = out_dir / "final.mp4"
    log.info("Assembled %s (%.1fs)", final, total)
    return final
