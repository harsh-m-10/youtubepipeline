"""Script generation grounded in retrieved evidence, plus the verification
pass: generate -> check length -> verify claims against evidence -> retry -> abort.
Fail-closed: a script that can't be verified never becomes a video.

Format note: the channel is informatory — scripts surface a surprising true thing,
go deeper with evidence, and end by asking viewers what they think (no verdict)."""

import logging

from src import config
from src.generate import evidence as evidence_mod
from src.generate import llm

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


def _generate(candidate: dict, evidence_block: str) -> dict:
    prompt = config.load_prompt(
        "script",
        belief=candidate["belief"],
        hook=candidate["hook"],
        min_words=config.TARGET_SCRIPT_WORDS[0],
        max_words=config.TARGET_SCRIPT_WORDS[1],
        floor=config.MIN_ACCEPTABLE_WORDS,
        evidence=evidence_block,
    )
    script = llm.complete_json(
        system="You write tight, evidence-grounded, fascinating informatory Shorts scripts. Respond only with valid JSON.",
        user=prompt,
    )
    if not script.get("beats"):
        raise RuntimeError(f"Script JSON missing beats: {list(script.keys())}")
    return script


def _word_count(script: dict) -> int:
    return sum(len(b["text"].split()) for b in script["beats"])


def _verify(script: dict, evidence_block: str) -> tuple[bool, list[str]]:
    narration = "\n".join(b["text"] for b in script["beats"])
    prompt = config.load_prompt("verify", script=narration, evidence=evidence_block)
    result = llm.complete_json(
        system="You are a strict fact-check gate. Respond only with valid JSON.",
        user=prompt,
        temperature=config.LLM_SCORE_TEMPERATURE,
    )
    return bool(result.get("passed")), result.get("failures", [])


def write_script(candidate: dict, snippets: list[dict]) -> dict:
    """Returns the verified script dict, with sources attached. Raises if no
    attempt passes both the length floor and the fact-check."""
    if not snippets:
        raise RuntimeError("No evidence gathered — refusing to script unsupported claims")
    evidence_block = evidence_mod.format_block(snippets)

    last_problem = "no attempts made"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        script = _generate(candidate, evidence_block)
        words = _word_count(script)
        if words < config.MIN_ACCEPTABLE_WORDS:
            last_problem = f"under-written ({words} words)"
            log.warning("Attempt %d %s — regenerating", attempt, last_problem)
            continue
        passed, failures = _verify(script, evidence_block)
        if not passed:
            last_problem = f"fact-check failures: {failures}"
            log.warning("Attempt %d failed verification: %s", attempt, failures)
            continue
        cited_ids = {c for b in script["beats"] for c in b.get("claims", [])}
        script["sources"] = [
            s for i, s in enumerate(snippets, 1) if f"E{i}" in cited_ids
        ] or snippets[:3]
        script["belief"] = candidate["belief"]
        log.info("Script verified on attempt %d (%d words): %s", attempt, words, script["title"])
        return script

    raise RuntimeError(f"Script failed after {MAX_ATTEMPTS} attempts; last problem: {last_problem}")


def full_description(script: dict) -> str:
    src_lines = "\n".join(f"- {s['title']}: {s['url']}" for s in script["sources"])
    has_s2 = any(s.get("source") == "Semantic Scholar" for s in script["sources"])
    s2_credit = "\nResearch via Semantic Scholar (semanticscholar.org)." if has_s2 else ""
    return (
        f"{script['description']}\n\n"
        "What do you think? Tell me in the comments.\n\n"
        f"Sources:\n{src_lines}\n\n"
        "Narration is AI-voiced. Every claim is sourced above."
        f"{s2_credit}\n"
        f"{config.MUSIC_CREDIT}\n"
        "#Shorts #RabbitHoleDaily"
    )


def caption_for_instagram(script: dict) -> str:
    """Instagram Reels caption: hook + description + engagement CTA + sources + hashtags."""
    src_names = ", ".join(s["title"].split(" (")[0] for s in script["sources"][:3])
    tags = list(dict.fromkeys(  # de-dupe, preserve order
        [t.lstrip("#").replace(" ", "") for t in script.get("hashtags", [])]
        + config.BRAND_HASHTAGS
    ))[: config.MAX_HASHTAGS]
    hashtag_line = " ".join(f"#{t}" for t in tags)
    return (
        f"{script['description']}\n\n"
        "What do you think?\n"
        "Tell me in the comments 👇\n\n"
        f"Sources: {src_names}\n"
        f"{config.MUSIC_CREDIT}\n\n"
        f"{hashtag_line}"
    )
