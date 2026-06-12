"""Hacker News via the Algolia API — keyless and CI-friendly.
Primary content source; the pipeline must work with HN alone."""

import requests

from src import config

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"


def fetch_threads(limit: int = config.HN_THREADS) -> list[dict]:
    """Return top front-page stories as normalized thread dicts."""
    resp = requests.get(
        ALGOLIA_URL,
        params={"tags": "front_page", "hitsPerPage": limit},
        timeout=20,
    )
    resp.raise_for_status()
    threads = []
    for hit in resp.json().get("hits", []):
        if not hit.get("title"):
            continue
        threads.append(
            {
                "source": "hackernews",
                "title": hit["title"],
                "url": hit.get("url")
                or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                "score": hit.get("points", 0),
                "num_comments": hit.get("num_comments", 0),
            }
        )
    return threads
