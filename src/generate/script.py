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


def _generate(candidate: dict, evidence_block: str, feedback: str = "") -> dict:
    prompt = config.load_prompt(
        "script",
        belief=candidate["belief"],
        hook=candidate["hook"],
        min_words=config.TARGET_SCRIPT_WORDS[0],
        max_words=config.TARGET_SCRIPT_WORDS[1],
        floor=config.MIN_ACCEPTABLE_WORDS,
        evidence=evidence_block,
    )
    if feedback:
        prompt += f"\n\nIMPORTANT — fix this from your previous attempt:\n{feedback}"
    script = llm.complete_json(
        system="You write tight, evidence-grounded, fascinating informatory Shorts scripts. Respond only with valid JSON.",
        user=prompt,
    )
    if not script.get("beats"):
        raise RuntimeError(f"Script JSON missing beats: {list(script.keys())}")
    return script


def _word_count(script: dict) -> int:
    return sum(len(b["text"].split()) for b in script["beats"])


_STOP = {"the", "a", "an", "and", "but", "or", "of", "to", "in", "on", "for", "is",
         "are", "was", "were", "it", "its", "this", "that", "these", "those", "with",
         "as", "at", "by", "be", "been", "you", "your", "they", "their", "we", "our",
         "not", "so", "more", "than", "from", "have", "has", "had", "can", "will"}


def _repetitive(script: dict, threshold: float = 0.3) -> str | None:
    """Detect near-duplicate sentences across the narration (the 'said the same
    thing 3 times' failure). Returns the offending pair, or None. Pure-Python,
    no LLM call — Jaccard overlap of content words."""
    import re

    text = " ".join(b["text"] for b in script["beats"])
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    sets = []
    for s in sents:
        words = {w for w in re.findall(r"[a-z0-9]+", s.lower())
                 if w not in _STOP and (len(w) > 2 or w.isdigit())}
        sets.append((s, words))
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a, b = sets[i][1], sets[j][1]
            if len(a) < 5 or len(b) < 5:
                continue
            overlap = len(a & b) / len(a | b)
            if overlap >= threshold:
                return f"'{sets[i][0]}' vs '{sets[j][0]}'"
    return None


def _verify(script: dict, evidence_block: str) -> tuple[bool, list[str]]:
    narration = "\n".join(b["text"] for b in script["beats"])
    prompt = config.load_prompt("verify", script=narration, evidence=evidence_block)
    result = llm.complete_json(
        system="You are a strict fact-check gate. Respond only with valid JSON.",
        user=prompt,
        temperature=config.LLM_SCORE_TEMPERATURE,
        model=config.LLM_SMALL_MODEL,
    )
    return bool(result.get("passed")), result.get("failures", [])


def write_script(candidate: dict, snippets: list[dict]) -> dict:
    """Returns the verified script dict, with sources attached. Raises if no
    attempt passes both the length floor and the fact-check."""
    if not snippets:
        raise RuntimeError("No evidence gathered — refusing to script unsupported claims")
    evidence_block = evidence_mod.format_block(snippets)

    def _finalize(s: dict) -> dict:
        cited_ids = {c for b in s["beats"] for c in b.get("claims", [])}
        s["sources"] = [
            snip for i, snip in enumerate(snippets, 1) if f"E{i}" in cited_ids
        ] or snippets[:3]
        s["belief"] = candidate["belief"]
        return s

    last_problem = "no attempts made"
    feedback = ""
    # A script that clears the HARD gates (length + fact-check) is publishable.
    # Repetition is a soft quality preference: we retry for a cleaner take, but
    # never fail the whole run over it — a slightly repetitive video beats none.
    best_publishable: dict | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        script = _generate(candidate, evidence_block, feedback)
        words = _word_count(script)
        if words < config.MIN_ACCEPTABLE_WORDS:
            last_problem = f"under-written ({words} words)"
            log.warning("Attempt %d %s — regenerating", attempt, last_problem)
            feedback = (
                f"Your last script was only {words} words — too short. Reach at least "
                f"{config.MIN_ACCEPTABLE_WORDS} words by adding NEW distinct facts or real "
                "context from the evidence (history, scale, who/why). Do NOT repeat or "
                "reword points you already made — repetition is rejected. If the evidence "
                "truly lacks more distinct material, that's fine, but use every distinct "
                "fact it does contain."
            )
            continue
        passed, failures = _verify(script, evidence_block)
        if not passed:
            last_problem = f"fact-check failures: {failures}"
            log.warning("Attempt %d failed verification: %s", attempt, failures)
            feedback = (
                "Some claims were not supported by the evidence. Remove or rephrase "
                "these so every statement is backed by the EVIDENCE block (keep the "
                f"length at {config.MIN_ACCEPTABLE_WORDS}+ words): {failures}"
            )
            continue
        # passed the hard gates — keep as fallback
        if best_publishable is None:
            best_publishable = _finalize(dict(script))
        dup = _repetitive(script)
        if dup:
            last_problem = f"repetitive ({dup})"
            log.warning("Attempt %d repetitive — retrying for a cleaner take: %s", attempt, dup)
            feedback = (
                "Your last script repeated the same point in different words: "
                f"{dup}. Rewrite so every sentence says something NEW. Replace the "
                "repeated sentence with a different sourced fact, or cut it."
            )
            continue
        log.info("Script verified on attempt %d (%d words): %s", attempt, words, script["title"])
        return _finalize(script)

    if best_publishable is not None:
        log.warning("Using best publishable script despite repetition (%s)", last_problem)
        return best_publishable

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
