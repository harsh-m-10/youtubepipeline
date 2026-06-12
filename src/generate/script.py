"""Script generation grounded in retrieved evidence, plus the verification
pass: generate -> verify claims against evidence -> regenerate once -> abort.
Fail-closed: a script that can't be verified never becomes a video."""

import logging

from src import config
from src.generate import evidence as evidence_mod
from src.generate import llm

log = logging.getLogger(__name__)


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
        system="You write tight, evidence-grounded Shorts scripts. Respond only with valid JSON.",
        user=prompt,
    )
    if not script.get("beats") or script.get("verdict") not in ("SURVIVES", "REJECTED"):
        raise RuntimeError(f"Script JSON missing beats/verdict: {list(script.keys())}")
    return script


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
    """Returns the verified script dict, with sources attached. Raises if
    verification fails twice."""
    evidence_block = evidence_mod.format_block(snippets)
    if not snippets:
        raise RuntimeError("No evidence gathered — refusing to script unsupported claims")

    for attempt in (1, 2):
        script = _generate(candidate, evidence_block)
        passed, failures = _verify(script, evidence_block)
        if passed:
            cited_ids = {c for b in script["beats"] for c in b.get("claims", [])}
            script["sources"] = [
                s for i, s in enumerate(snippets, 1) if f"E{i}" in cited_ids
            ] or snippets[:3]
            script["belief"] = candidate["belief"]
            log.info("Script verified on attempt %d: %s", attempt, script["title"])
            return script
        log.warning("Verification failed (attempt %d): %s", attempt, failures)

    raise RuntimeError(f"Script failed fact-check twice; aborting run. Failures: {failures}")


def full_description(script: dict) -> str:
    src_lines = "\n".join(f"- {s['title']}: {s['url']}" for s in script["sources"])
    return (
        f"{script['description']}\n\n"
        f"Sources:\n{src_lines}\n\n"
        "Narration is AI-voiced. Every claim is sourced above.\n"
        "#Shorts #NullHypothesis"
    )
