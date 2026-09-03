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
# Groq free tier is ~8000 tokens/min PER MODEL (separate buckets), and a
# request's prompt+max_tokens is charged against it up front. Route quality
# calls (idea + script generation) to the big model and mechanical calls
# (scoring, verification, dedupe, evidence queries) to the small one — this
# spreads load across two TPM buckets and roughly halves rate-limit stalls.
# llama-3.3-70b-versatile and llama-3.1-8b-instant are both decommissioned by
# Groq on 2026-08-16 (per console.groq.com/docs/deprecations); gpt-oss-120b/20b
# are the recommended successors. Still two separate TPM buckets, JSON mode OK.
LLM_MODEL = "openai/gpt-oss-120b"         # quality
LLM_SMALL_MODEL = "openai/gpt-oss-20b"    # mechanical
LLM_MODELS = [LLM_MODEL, LLM_SMALL_MODEL]  # fallback order
LLM_TEMPERATURE = 0.8
LLM_SCORE_TEMPERATURE = 0.2  # scoring/verification should be deterministic-ish
LLM_MAX_RATE_WAIT = 65  # cap a single rate-limit wait (TPM window is ~60s)

# --- Evidence ---
S2_API_KEY = os.getenv("S2_API_KEY", "")  # Semantic Scholar; degrades to Wikipedia-only if unset
S2_MIN_INTERVAL = 1.1  # seconds between S2 calls (their limit is 1 req/sec cumulative)
# Groq free tier caps a single request at 6000 input tokens, so the evidence
# block fed to the script/verify prompts must stay small. Keep a balanced mix.
MAX_EVIDENCE_SNIPPETS = 6
EVIDENCE_SNIPPET_CHARS = 550
# Support is scored 0-10 (see prompts/support.txt), not a pass/fail veto.
# The pipeline publishes the best-supported candidate of the day; only those
# the evidence actively CONTRADICTS (or has nothing on) fall below this floor
# and are skipped. Kept low on purpose: an unconfirmed-but-not-refuted fact is
# publishable, a refuted myth is not. Raising the score gate to zero videos was
# the failure this replaces.
MIN_SUPPORT_SCORE = 4.0
# How many top-ranked candidates to run through evidence before giving up for
# the day. We stop early the moment one scores STRONG (see pipeline). Kept
# generous because dedupe (63+ videos of history) and myth-rejection thin the
# pool fast — a narrow window leaves nothing to publish on an ordinary day.
EVIDENCE_CANDIDATE_LIMIT = 8
STRONG_SUPPORT_SCORE = 8.0  # a candidate this well-supported is used immediately

# --- Sources ---
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = "rabbit-hole-daily-pipeline/0.1 (by /u/rabbitholedaily-bot)"
SUBREDDITS = ["economics", "dataisbeautiful", "science", "AskHistorians", "personalfinance"]
THREADS_PER_SUBREDDIT = 5
HN_THREADS = 15

# --- Hypothesis generation ---
CANDIDATES_PER_RUN = 15
# Recalibrated 2026-07-03: gpt-oss-20b actually follows the "most candidates
# score 4-6" instruction (llama-8b inflated everything to 8-10), so a 7.0 gate
# starved the channel — best-of-day hovered at 7.0-7.5 with many no-video runs.
# 6.0 = "solid, publishable" on the new scale; the gate still blocks bad batches.
MIN_SCORE_TO_PROCEED = 6.0
HISTORY_DEDUPE_WINDOW = 100  # compare against last N published hypotheses

# --- Media ---
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
TTS_VOICE = "en-US-AvaMultilingualNeural"  # energetic female voice
TTS_RATE = "+15%"  # brisk pacing keeps Shorts retention
VIDEO_W, VIDEO_H = 1080, 1920
# Title card displays while beat 1 (intro) is narrated; the end card displays
# while the closing beat is narrated, then holds briefly.
END_CARD_HOLD_SECONDS = 1.5
MUSIC_VOLUME = 0.12
# Music tracks are Kevin MacLeod / incompetech.com under CC BY 4.0 — credit required
MUSIC_CREDIT = "Music by Kevin MacLeod (incompetech.com), licensed under CC BY 4.0"
TARGET_SCRIPT_WORDS = (150, 210)  # ~55-70s at +15% narration pace
MIN_ACCEPTABLE_WORDS = 130  # regenerate if the LLM under-writes

# --- Publishing ---
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN", "")
YT_CATEGORY_ID = "27"  # Education

# Instagram Reels via official Meta Graph API
IG_USER_ID = os.getenv("IG_USER_ID", "")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "")
# Classic GitHub PAT (repo scope) so CI can push the refreshed IG token back
# into the IG_ACCESS_TOKEN secret — keeps the 60-day token alive indefinitely.
GH_PAT = os.getenv("GH_PAT", "")
GH_REPO = os.getenv("GITHUB_REPOSITORY", "harsh-m-10/youtubepipeline")

BRAND_NAME = "Rabbit Hole Daily"
# Brand hashtags always appended to the Instagram caption (merged with per-video tags)
BRAND_HASHTAGS = ["rabbitholedaily", "didyouknow", "facts", "interesting", "learnsomething"]
MAX_HASHTAGS = 20

# WhatsApp alerts via CallMeBot (free personal gateway)
WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE", "")  # with country code, e.g. +91XXXXXXXXXX
CALLMEBOT_API_KEY = os.getenv("CALLMEBOT_API_KEY", "")


def load_prompt(name: str, **kwargs) -> str:
    """Load a prompt template and substitute <<key>> placeholders.
    Uses <<>> tokens instead of str.format so prompts can contain JSON braces."""
    text = (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
    for key, value in kwargs.items():
        text = text.replace(f"<<{key}>>", str(value))
    return text
