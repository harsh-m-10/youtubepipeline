"""Hypothesis generation: overgenerate candidates from source threads,
score them with a second LLM pass, dedupe against publish history,
return the ranked list. The quality gate (MIN_SCORE_TO_PROCEED) replaces
the human editor."""

import json
import logging

from src import config
from src.generate import llm

log = logging.getLogger(__name__)


def load_history() -> list[dict]:
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    return []


def save_to_history(entry: dict) -> None:
    history = load_history()
    history.append(entry)
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.STATE_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def generate_candidates(threads: list[dict], count: int = config.CANDIDATES_PER_RUN) -> list[dict]:
    threads_text = "\n".join(
        f"- [{t['source']}] {t['title']} ({t['url']}) — {t['score']} points, {t['num_comments']} comments"
        for t in threads
    )
    prompt = config.load_prompt("hypothesis", count=count, threads=threads_text)
    result = llm.complete_json(
        system="You generate testable, clickable hypothesis ideas. Respond only with valid JSON.",
        user=prompt,
    )
    candidates = result.get("candidates", [])
    log.info("Generated %d candidates", len(candidates))
    return candidates


def score_candidates(candidates: list[dict], calibration: str = "") -> list[dict]:
    """Attach score/duplicate/rationale to each candidate, return ranked (best first).
    `calibration` is an optional audience-performance hint (see src/analytics.py)."""
    history = load_history()
    recent_titles = [h["belief"] for h in history[-config.HISTORY_DEDUPE_WINDOW:]]
    history_text = "\n".join(f"- {t}" for t in recent_titles) or "(none yet)"
    candidates_text = "\n".join(
        f"[{i}] BELIEF: {c['belief']}\n    HOOK: {c['hook']}\n    TEST: {c['test_angle']}"
        for i, c in enumerate(candidates)
    )
    prompt = config.load_prompt(
        "score", history=history_text, candidates=candidates_text, calibration=calibration
    )
    result = llm.complete_json(
        system="You are a harsh, calibrated content editor. Respond only with valid JSON.",
        user=prompt,
        temperature=config.LLM_SCORE_TEMPERATURE,
        model=config.LLM_SMALL_MODEL,
    )
    by_index = {s["index"]: s for s in result.get("scores", [])}
    for i, c in enumerate(candidates):
        s = by_index.get(i, {})
        c["score"] = float(s.get("score", 0))
        c["duplicate"] = bool(s.get("duplicate", False))
        c["rationale"] = s.get("rationale", "")
    ranked = sorted(
        (c for c in candidates if not c["duplicate"]),
        key=lambda c: c["score"],
        reverse=True,
    )
    return ranked


def is_duplicate(candidate: dict) -> bool:
    """Focused LLM check of one candidate against publish history. More reliable
    than the duplicate flag inside the scoring rubric, which misses rewordings."""
    history = load_history()
    recent = [h["belief"] for h in history[-config.HISTORY_DEDUPE_WINDOW:]]
    if not recent:
        return False
    prompt = config.load_prompt(
        "dedupe",
        candidate=candidate["belief"],
        history="\n".join(f"- {b}" for b in recent),
    )
    result = llm.complete_json(
        system="You detect duplicate topics. Respond only with valid JSON.",
        user=prompt,
        temperature=0.0,
        model=config.LLM_SMALL_MODEL,
    )
    if result.get("duplicate"):
        log.info("Duplicate of published topic %r: %s",
                 result.get("matched_title"), candidate["belief"])
        return True
    return False


def pick_best(threads: list[dict]) -> dict | None:
    """Full pipeline stage: generate -> score -> gate. None means no video today."""
    candidates = generate_candidates(threads)
    if not candidates:
        return None
    ranked = score_candidates(candidates)
    if not ranked or ranked[0]["score"] < config.MIN_SCORE_TO_PROCEED:
        best = ranked[0]["score"] if ranked else 0
        log.info("No candidate cleared the %.1f bar (best: %.1f) — skipping today",
                 config.MIN_SCORE_TO_PROCEED, best)
        return None
    return ranked[0]
