"""Central configuration. All secrets come from environment variables
(GitHub Actions secrets in CI, .env file locally)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out"
STATE_FILE = ROOT / "state" / "history.json"
PROMPTS_DIR = ROOT / "prompts"
ASSETS_DIR = ROOT / "assets"

# --- LLM ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]  # primary, fallback
LLM_TEMPERATURE = 0.8
LLM_SCORE_TEMPERATURE = 0.2  # scoring/verification should be deterministic-ish

# --- Sources ---
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = "null-hypothesis-pipeline/0.1 (by /u/nullhypothesis-bot)"
SUBREDDITS = ["economics", "dataisbeautiful", "science", "AskHistorians", "personalfinance"]
THREADS_PER_SUBREDDIT = 5
HN_THREADS = 15

# --- Hypothesis generation ---
CANDIDATES_PER_RUN = 15
MIN_SCORE_TO_PROCEED = 7.0
HISTORY_DEDUPE_WINDOW = 100  # compare against last N published hypotheses

# --- Media ---
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
TTS_VOICE = "en-US-AndrewNeural"
TTS_RATE = "+8%"  # slightly brisk pacing suits Shorts
VIDEO_W, VIDEO_H = 1080, 1920
TITLE_CARD_SECONDS = 2.5
VERDICT_CARD_SECONDS = 3.0
MUSIC_VOLUME = 0.12
TARGET_SCRIPT_WORDS = (110, 170)  # ~45-75s at Shorts narration pace

# --- Publishing ---
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN", "")
YT_CATEGORY_ID = "27"  # Education

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def load_prompt(name: str, **kwargs) -> str:
    """Load a prompt template and substitute <<key>> placeholders.
    Uses <<>> tokens instead of str.format so prompts can contain JSON braces."""
    text = (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
    for key, value in kwargs.items():
        text = text.replace(f"<<{key}>>", str(value))
    return text
