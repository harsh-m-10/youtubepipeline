"""PHASE 0 — the go/no-go click test.

Fetches live threads, generates hypotheses in batches, scores them, and writes
a ranked review file. The bar: out of 50, would you personally click at least 5?

Usage:
    python scripts/test_hypotheses.py            # 50 hypotheses (default)
    python scripts/test_hypotheses.py --count 20 # quicker smoke test
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.generate import hypothesis
from src.sources import reddit

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("test_hypotheses")

BATCH_SIZE = 15  # candidates per LLM call; batching keeps each call focused


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50, help="total hypotheses to generate")
    args = parser.parse_args()

    log.info("Fetching source threads...")
    threads = reddit.fetch_all_threads()
    log.info("Got %d threads (%d from HN)", len(threads),
             sum(1 for t in threads if t["source"] == "hackernews"))
    if not threads:
        log.error("No threads fetched — check network")
        sys.exit(1)

    candidates: list[dict] = []
    while len(candidates) < args.count:
        n = min(BATCH_SIZE, args.count - len(candidates))
        log.info("Generating batch of %d (have %d/%d)...", n, len(candidates), args.count)
        candidates.extend(hypothesis.generate_candidates(threads, count=n))

    log.info("Scoring %d candidates...", len(candidates))
    ranked = hypothesis.score_candidates(candidates)

    config.OUT_DIR.mkdir(exist_ok=True)
    out_file = config.OUT_DIR / "hypotheses_review.md"
    lines = [
        "# Hypothesis Click-Test\n",
        f"Generated {len(ranked)} candidates. **The bar: would you click at least 5?**\n",
        "Tick the ones you'd click:\n",
    ]
    for i, c in enumerate(ranked, 1):
        lines.append(
            f"- [ ] **{i}. [{c['score']:.1f}] {c['hook']}**\n"
            f"      - Belief: {c['belief']}\n"
            f"      - Test: {c['test_angle']}\n"
            f"      - Editor: {c['rationale']}\n"
            f"      - Source: {c['source_title']}\n"
        )
    out_file.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{'=' * 70}")
    print(f"TOP 10 OF {len(ranked)}:")
    print(f"{'=' * 70}")
    for i, c in enumerate(ranked[:10], 1):
        print(f"{i:2}. [{c['score']:.1f}] {c['hook']}")
        print(f"     belief: {c['belief']}")
    print(f"\nFull ranked list: {out_file}")
    print("THE BAR: would you personally click at least 5 of the 50?")


if __name__ == "__main__":
    main()
