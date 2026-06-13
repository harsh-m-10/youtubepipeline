"""Word timestamps -> ASS karaoke subtitles (big word-by-word captions,
the standard high-retention Shorts style). Narration starts at t=0, so caption
times match word timestamps directly. Captions sit in the lower third so they
never cover the text on the title/end cards."""

from pathlib import Path

from src import config

WORDS_PER_LINE = 2  # short lines: big text without escaping the frame edges
HIGHLIGHT = "&H004DD2FF&"  # warm yellow 255,210,77 — ASS colors are &HAABBGGRR

ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {config.VIDEO_W}
PlayResY: {config.VIDEO_H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Montserrat,84,&H00FFFFFF,{HIGHLIGHT},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,0,2,100,100,430,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(words: list[dict], out_dir: Path) -> Path:
    """Group words into short lines; karaoke-highlight each word as spoken."""
    lines = []
    for i in range(0, len(words), WORDS_PER_LINE):
        group = words[i : i + WORDS_PER_LINE]
        start = group[0]["start"]
        end = group[-1]["end"]
        parts = []
        for w in group:
            # \kf duration is in centiseconds
            dur_cs = max(1, round((w["end"] - w["start"]) * 100))
            parts.append(f"{{\\kf{dur_cs}}}{w['word'].upper()}")
        text = " ".join(parts)
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{text}")

    ass_path = out_dir / "captions.ass"
    ass_path.write_text(ASS_HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return ass_path
