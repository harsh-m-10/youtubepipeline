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
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
# Wikimedia returns 403 for generic client UAs; they require a descriptive one
HEADERS = {"User-Agent": "NullHypothesisBot/0.1 (personal research pipeline)"}

_last_s2_call = 0.0  # module-level clock to honor S2's 1 req/sec cumulative limit


def _s2_throttle() -> None:
    global _last_s2_call
    wait = config.S2_MIN_INTERVAL - (time.monotonic() - _last_s2_call)
    if wait > 0:
        time.sleep(wait)
    _last_s2_call = time.monotonic()


def _wiki_search(query: str, limit: int = 3) -> list[dict]:
    try:
        resp = requests.get(
            WIKI_API,
            headers=HEADERS,
            params={
                "action": "query", "format": "json", "list": "search",
                "srsearch": query, "srlimit": limit,
            },
            timeout=20,
        )
        resp.raise_for_status()
        titles = [r["title"] for r in resp.json()["query"]["search"]]
        if not titles:
            return []
        resp = requests.get(
            WIKI_API,
            headers=HEADERS,
            params={
                "action": "query", "format": "json", "prop": "extracts",
                "exintro": 1, "explaintext": 1, "exsentences": 6,
                "titles": "|".join(titles),
            },
            timeout=20,
        )
        resp.raise_for_status()
        pages = resp.json()["query"]["pages"].values()
        return [
            {
                "source": "Wikipedia",
                "title": p["title"],
                "url": f"https://en.wikipedia.org/wiki/{p['title'].replace(' ', '_')}",
                "snippet": p.get("extract", "").strip(),
            }
            for p in pages
            if p.get("extract")
        ]
    except Exception as exc:
        log.warning("Wikipedia search failed for %r: %s", query, exc)
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
                "snippet": (p.get("abstract") or "").strip()[:1200],
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
            "Each query must be a SHORT PLAIN keyword phrase (2-5 words), no boolean\n"
            "operators, no quotes, no field prefixes. JSON:\n"
            '{"wikipedia": ["q1", "q2"], "academic": ["q1", "q2"]}'
        ),
        temperature=0.3,
    )
    snippets: list[dict] = []
    for q in result.get("wikipedia", [])[:2]:
        snippets.extend(_wiki_search(q))
    for q in result.get("academic", [])[:2]:
        snippets.extend(_scholar_search(q))
    # de-duplicate by url
    seen, unique = set(), []
    for s in snippets:
        if s["url"] not in seen:
            seen.add(s["url"])
            unique.append(s)
    log.info("Gathered %d evidence snippets", len(unique))
    return unique


def format_block(snippets: list[dict]) -> str:
    return "\n\n".join(
        f"[E{i}] ({s['source']}) {s['title']}\nURL: {s['url']}\n{s['snippet']}"
        for i, s in enumerate(snippets, 1)
    )
