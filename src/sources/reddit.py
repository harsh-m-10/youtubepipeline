"""Reddit top weekly posts via PRAW in read-only mode (client id/secret only).
Optional source — if credentials are missing or Reddit blocks the CI IP,
returns an empty list and the pipeline continues on HN alone."""

import logging

from src import config

log = logging.getLogger(__name__)


def fetch_threads() -> list[dict]:
    if not (config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET):
        log.warning("Reddit credentials not set; skipping Reddit source")
        return []
    try:
        import praw

        reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT,
        )
        threads = []
        for sub in config.SUBREDDITS:
            for post in reddit.subreddit(sub).top(
                time_filter="week", limit=config.THREADS_PER_SUBREDDIT
            ):
                threads.append(
                    {
                        "source": f"r/{sub}",
                        "title": post.title,
                        "url": f"https://reddit.com{post.permalink}",
                        "score": post.score,
                        "num_comments": post.num_comments,
                    }
                )
        return threads
    except Exception as exc:
        log.warning("Reddit fetch failed (%s); continuing without it", exc)
        return []


def fetch_all_threads() -> list[dict]:
    """All sources combined, HN first."""
    from src.sources import hackernews

    return hackernews.fetch_threads() + fetch_threads()
