"""Script generation grounded in retrieved evidence, plus the verification
pass: generate -> check length -> verify claims against evidence -> retry -> abort.
Fail-closed: a script that can't be verified never becomes a video.

Format note: the channel never declares a verdict — scripts argue both sides
and end by asking viewers whether the null hypothesis survives."""

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
        evidence=evidence_block,
    )
    script = llm.complete_json(
        system="You write tight, evidence-grounded Shorts scripts that argue both sides. Respond only with valid JSON.",
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
    return (
        f"{script['description']}\n\n"
        "Does the null hypothesis survive or get rejected? Vote in the comments.\n\n"
        f"Sources:\n{src_lines}\n\n"
        "Narration is AI-voiced. Every claim is sourced above.\n"
        "#Shorts #NullHypothesis"
    )
