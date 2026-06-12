"""Evidence retrieval: real snippets from Wikipedia and Semantic Scholar.
These snippets become the ONLY allowed factual basis for the script —
this is the hallucination guard that replaces a human fact-checker."""

import logging

import requests

from src import config
from src.generate import llm

log = logging.getLogger(__name__)

WIKI_API = "https://en.wikipedia.org/w/api.php"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"


def _wiki_search(query: str, limit: int = 3) -> list[dict]:
    try:
        resp = requests.get(
            WIKI_API,
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
    try:
        resp = requests.get(
            S2_API,
            params={
                "query": query,
                "fields": "title,abstract,year,url,citationCount",
                "limit": limit,
            },
            timeout=20,
        )
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
            'Give 2 Wikipedia search queries and 2 academic search queries as JSON:\n'
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
