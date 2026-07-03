"""Evidence retrieval: real snippets from Wikipedia and Semantic Scholar.
These snippets become the ONLY allowed factual basis for the script —
this is the hallucination guard that replaces a human fact-checker."""

import logging
import time

import requests

from src import config
from src.generate import llm

log = logging.getLogger(__name__)

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKTIONARY_API = "https://en.wiktionary.org/w/api.php"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
# Wikimedia returns 403 for generic client UAs; they require a descriptive one
HEADERS = {"User-Agent": "RabbitHoleDailyBot/0.1 (personal research pipeline)"}

_last_s2_call = 0.0  # module-level clock to honor S2's 1 req/sec cumulative limit
_last_wiki_call = 0.0  # Wikimedia 429s unauthenticated bursts; stay polite


def _s2_throttle() -> None:
    global _last_s2_call
    wait = config.S2_MIN_INTERVAL - (time.monotonic() - _last_s2_call)
    if wait > 0:
        time.sleep(wait)
    _last_s2_call = time.monotonic()


def _wikimedia_get(api: str, params: dict) -> dict:
    """Throttled GET against a Wikimedia API, with one retry on 429."""
    global _last_wiki_call
    for attempt in range(2):
        wait = 0.5 - (time.monotonic() - _last_wiki_call)
        if wait > 0:
            time.sleep(wait)
        _last_wiki_call = time.monotonic()
        resp = requests.get(api, headers=HEADERS, params=params, timeout=20)
        if resp.status_code == 429 and attempt == 0:
            log.info("Wikimedia rate-limited, waiting 5s")
            time.sleep(5)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("unreachable")


_WINDOW_STOP = {"the", "a", "an", "and", "but", "or", "of", "to", "in", "on", "for",
                "is", "are", "was", "were", "it", "its", "this", "that", "with", "as",
                "at", "by", "be", "not", "from", "has", "had", "have", "which", "their"}


def _relevant_window(text: str, context: str, chars: int) -> str:
    """The sentence run most relevant to `context` (the belief being checked).
    Facts usually live deep in the article body, not the intro — intro-only
    snippets made the support gate reject true-but-buried facts."""
    import re

    # split on newlines as well: extracts plaintext is full of period-less
    # header/list lines that would otherwise glue into one giant "sentence"
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    ctx_words = {w for w in re.findall(r"[a-z0-9]+", context.lower())
                 if w not in _WINDOW_STOP and len(w) > 2}
    best_i, best_score = 0, 0
    for i, s in enumerate(sents):
        score = len(ctx_words & set(re.findall(r"[a-z0-9]+", s.lower())))
        if score > best_score:
            best_i, best_score = i, score
    if best_score == 0:
        return text[:chars]  # nothing matched — fall back to the intro
    window = " ".join(sents[max(0, best_i - 1): best_i + 3])
    return window[:chars]


def _wiki_search(query: str, context: str = "", limit: int = 3) -> list[dict]:
    try:
        data = _wikimedia_get(
            WIKI_API,
            {
                "action": "query", "format": "json", "list": "search",
                "srsearch": query, "srlimit": limit,
            },
        )
        titles = [r["title"] for r in data["query"]["search"]]
        out = []
        # Full-page plaintext extracts are limited to one page per request,
        # so fetch per title; the relevance window keeps snippets small.
        for title in titles:
            data = _wikimedia_get(
                WIKI_API,
                {
                    "action": "query", "format": "json", "prop": "extracts",
                    "explaintext": 1, "titles": title, "redirects": 1,
                },
            )
            for p in data["query"]["pages"].values():
                extract = p.get("extract", "").strip()
                if not extract:
                    continue
                out.append(
                    {
                        "source": "Wikipedia",
                        "title": p["title"],
                        "url": f"https://en.wikipedia.org/wiki/{p['title'].replace(' ', '_')}",
                        "snippet": _relevant_window(
                            extract, context or query, config.EVIDENCE_SNIPPET_CHARS
                        ),
                    }
                )
        return out
    except Exception as exc:
        log.warning("Wikipedia search failed for %r: %s", query, exc)
        return []


def _word_candidates(belief: str) -> list[str]:
    """Words the belief is ABOUT (quoted, or following 'the word/term/...') —
    these get a Wiktionary lookup, the canonical source for etymology facts
    that Wikipedia's search can't find."""
    import re

    quoted = re.findall(r"['\"‘“]([A-Za-z][A-Za-z-]{1,24})['\"’”]", belief)
    named = re.findall(
        r"\b(?:word|term|adjective|noun|verb|phrase)\s+['\"‘“]?([A-Za-z-]{2,24})",
        belief, flags=re.IGNORECASE,
    )
    seen, out = set(), []
    for w in quoted + named:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            out.append(lw)
    return out[:2]


def _wiktionary_lookup(word: str, context: str) -> list[dict]:
    try:
        data = _wikimedia_get(
            WIKTIONARY_API,
            {
                "action": "query", "format": "json", "prop": "extracts",
                "explaintext": 1, "titles": word, "redirects": 1,
            },
        )
        out = []
        for p in data["query"]["pages"].values():
            extract = p.get("extract", "").strip()
            if not extract:
                continue
            out.append(
                {
                    "source": "Wiktionary",
                    "title": p["title"],
                    "url": f"https://en.wiktionary.org/wiki/{p['title'].replace(' ', '_')}",
                    "snippet": _relevant_window(extract, context, config.EVIDENCE_SNIPPET_CHARS),
                }
            )
        return out
    except Exception as exc:
        log.warning("Wiktionary lookup failed for %r: %s", word, exc)
        return []


def _scholar_search(query: str, limit: int = 4) -> list[dict]:
    headers = dict(HEADERS)
    if config.S2_API_KEY:
        headers["x-api-key"] = config.S2_API_KEY
    try:
        # S2 allows 1 req/sec cumulative; throttle, then retry a couple times on 429
        for attempt in range(3):
            _s2_throttle()
            resp = requests.get(
                S2_API,
                headers=headers,
                params={
                    "query": query,
                    "fields": "title,abstract,year,url,citationCount",
                    "limit": limit,
                },
                timeout=20,
            )
            if resp.status_code != 429:
                break
            wait = 2 * (attempt + 1)
            log.info("Semantic Scholar rate-limited, waiting %ss", wait)
            time.sleep(wait)
        resp.raise_for_status()
        papers = resp.json().get("data") or []
        return [
            {
                "source": "Semantic Scholar",
                "title": f"{p['title']} ({p.get('year', 'n.d.')}, {p.get('citationCount', 0)} citations)",
                "url": p.get("url", ""),
                "snippet": (p.get("abstract") or "").strip()[: config.EVIDENCE_SNIPPET_CHARS],
            }
            for p in papers
            if p.get("abstract")
        ]
    except Exception as exc:
        log.warning("Semantic Scholar search failed for %r: %s", query, exc)
        return []


def gather(candidate: dict) -> list[dict]:
    """Ask the LLM for search queries, then retrieve real snippets."""
    result = llm.complete_json(
        system="You design literature/encyclopedia search queries. Respond only with valid JSON.",
        user=(
            "We need evidence FOR and AGAINST this belief:\n"
            f"BELIEF: {candidate['belief']}\n"
            f"TEST ANGLE: {candidate['test_angle']}\n\n"
            "Give 2 Wikipedia search queries and 2 academic search queries.\n"
            "For Wikipedia: think about WHICH ARTICLE would document this fact, and\n"
            "write the query like that article's likely TITLE (the subject's name,\n"
            "e.g. 'Henry Ford', 'History of Coca-Cola'), not a description of the fact.\n"
            "Each query must be a SHORT PLAIN keyword phrase (2-5 words), no boolean\n"
            "operators, no quotes, no field prefixes. JSON:\n"
            '{"wikipedia": ["q1", "q2"], "academic": ["q1", "q2"]}'
        ),
        temperature=0.3,
        model=config.LLM_SMALL_MODEL,
    )
    wiki, scholar = [], []
    # etymology/word beliefs: Wiktionary is the canonical source and goes first
    for w in _word_candidates(candidate["belief"]):
        wiki.extend(_wiktionary_lookup(w, context=candidate["belief"]))
    for q in result.get("wikipedia", [])[:2]:
        wiki.extend(_wiki_search(q, context=candidate["belief"]))
    for q in result.get("academic", [])[:2]:
        scholar.extend(_scholar_search(q))

    # de-duplicate by url within each source
    def _dedupe(items):
        seen, out = set(), []
        for s in items:
            if s["url"] not in seen:
                seen.add(s["url"])
                out.append(s)
        return out

    wiki, scholar = _dedupe(wiki), _dedupe(scholar)
    # Balanced mix capped at MAX_EVIDENCE_SNIPPETS to stay under the 6000-token
    # request limit — interleave so both Wikipedia and academic sources survive.
    half = config.MAX_EVIDENCE_SNIPPETS // 2
    unique = wiki[:half] + scholar[: config.MAX_EVIDENCE_SNIPPETS - half]
    if len(unique) < config.MAX_EVIDENCE_SNIPPETS:  # backfill if one source was thin
        extra = (wiki[half:] + scholar[config.MAX_EVIDENCE_SNIPPETS - half:])
        unique += extra[: config.MAX_EVIDENCE_SNIPPETS - len(unique)]
    log.info("Gathered %d evidence snippets (%d wiki, %d academic)",
             len(unique), len(wiki), len(scholar))
    return unique


def supports(candidate: dict, snippets: list[dict]) -> bool:
    """True if the gathered evidence actually backs the candidate's core claim.
    The hypothesis generator states beliefs confidently whether or not they are
    real; topically-adjacent snippets used to slip through because the script
    verifier exempted the belief itself. This gate kills invented facts before
    any script tokens are spent on them."""
    prompt = config.load_prompt(
        "support", claim=candidate["belief"], evidence=format_block(snippets)
    )
    result = llm.complete_json(
        system="You are a strict pre-production fact-check gate. Respond only with valid JSON.",
        user=prompt,
        temperature=config.LLM_SCORE_TEMPERATURE,
        model=config.LLM_SMALL_MODEL,
    )
    if not result.get("supported"):
        log.warning("Belief not backed by evidence (%s): %s",
                    result.get("reason", "no reason given"), candidate["belief"])
        return False
    return True


def format_block(snippets: list[dict]) -> str:
    return "\n\n".join(
        f"[E{i}] ({s['source']}) {s['title']}\nURL: {s['url']}\n{s['snippet']}"
        for i, s in enumerate(snippets, 1)
    )
