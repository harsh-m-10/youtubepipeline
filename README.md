# Rabbit Hole Daily — Automated Shorts Pipeline

Fully automated Shorts factory for "Rabbit Hole Daily": scrapes trending discussions,
surfaces a weird-but-true everyday fact, writes a fact-checked informatory script,
narrates it with TTS, assembles a captioned vertical video, and cross-posts it to
YouTube (**private**) and Instagram Reels. Your only job: tap "publish" on your
phone when the WhatsApp message arrives.

```
HN/Reddit → Groq (idea + score) → Wikipedia/Semantic Scholar (evidence)
→ Groq (script + fact-check gate) → edge-tts (voice + word timings)
→ Pexels + Pillow (visuals) → ffmpeg → YouTube (private) + Instagram Reels → WhatsApp
```

## One-time setup

### 1. Local environment
```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
# ffmpeg must be on PATH: winget install ffmpeg
```
Create `.env` in the repo root (never committed):
```
GROQ_API_KEY=...
PEXELS_API_KEY=...
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
YT_CLIENT_ID=...
YT_CLIENT_SECRET=...
YT_REFRESH_TOKEN=...
WHATSAPP_PHONE=+91XXXXXXXXXX
CALLMEBOT_API_KEY=...
```

### 2. API keys (all free)
| Key | Where |
|---|---|
| `GROQ_API_KEY` | console.groq.com → API Keys |
| `PEXELS_API_KEY` | pexels.com/api |
| `REDDIT_CLIENT_*` | reddit.com/prefs/apps → create "script" app (optional — HN works alone) |
| `YT_*` | see `scripts/get_youtube_token.py` docstring (Google Cloud + OAuth; scopes: upload + force-ssl for auto-comments) |
| `S2_API_KEY` | semanticscholar.org/product/api (free; richer academic evidence) |
| `IG_*` | see `scripts/get_instagram_token.py` docstring (IG Creator account + Meta app) |
| `GH_PAT` | github.com/settings/tokens → classic token, `repo` scope (lets CI refresh the IG token secret itself) |
| `WHATSAPP_*` | CallMeBot (free): save +34 644 51 95 23 as a contact, WhatsApp it the message "I allow callmebot to send me messages", it replies with your API key |

### 3. Assets
- `assets/fonts/` — one bold `.ttf` (e.g. Montserrat ExtraBold from Google Fonts)
- `assets/music/` — `.mp3` background tracks; bundled tracks are Kevin MacLeod / incompetech.com (CC BY 4.0, credited in every description). Random track per video.

### 4. GitHub
Push to a **private** repo, add every `.env` key as a repo secret
(Settings → Secrets and variables → Actions). The workflow
(`.github/workflows/daily.yml`) runs daily at 08:00 IST and can be triggered
manually from the Actions tab (with an optional dry-run flag).

## Usage

```bash
# PHASE 0 GATE — run this first. Would you click at least 5 of the 50?
python scripts/test_hypotheses.py

# Full local dry run: produces out/<date>/final.mp4, no upload
python -m src.pipeline --dry-run

# Full run incl. upload (same thing CI does daily)
python -m src.pipeline
```

## Design notes
- **Quality gate replaces the editor:** 15 candidates/run are scored 1–10 by a
  second LLM pass; if none scores ≥ 7.0 (`MIN_SCORE_TO_PROCEED` in `src/config.py`),
  the run exits with no video. Some days produce nothing — that's intentional.
- **Hallucination guard replaces the fact-checker:** the script LLM may only use
  facts from retrieved Wikipedia/Semantic Scholar snippets, and a separate
  verification pass rejects unsupported claims. Fails twice → run aborts.
- **Fail-closed everywhere:** any stage error → WhatsApp alert, no upload.
- **Knobs** live in `src/config.py`; **editorial voice** lives in `prompts/*.txt` —
  tune prompts without touching code.
- Uploads carry `containsSyntheticMedia: true` (YouTube AI-voice disclosure) and
  cite all sources in the description.
