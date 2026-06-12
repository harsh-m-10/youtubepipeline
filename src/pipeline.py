"""End-to-end orchestrator. Fail-closed: any stage failure means no upload,
and a WhatsApp alert with the stage name.

Usage:
    python -m src.pipeline             # full run (CI entrypoint)
    python -m src.pipeline --dry-run   # everything except upload/history/notify
"""

import argparse
import datetime
import json
import logging
import sys

from src import config
from src.generate import evidence, hypothesis, script as script_mod
from src.media import assemble, captions, tts, visuals
from src.publish import notify, youtube
from src.sources import reddit

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pipeline")


def run(dry_run: bool = False) -> None:
    stage = "init"
    try:
        out_dir = config.OUT_DIR / datetime.date.today().isoformat()
        out_dir.mkdir(parents=True, exist_ok=True)

        stage = "source"
        threads = reddit.fetch_all_threads()
        if not threads:
            raise RuntimeError("No source threads fetched")
        log.info("Fetched %d threads", len(threads))

        stage = "hypothesize"
        candidates = hypothesis.generate_candidates(threads)
        ranked = hypothesis.score_candidates(candidates)
        if not ranked or ranked[0]["score"] < config.MIN_SCORE_TO_PROCEED:
            best = ranked[0]["score"] if ranked else 0.0
            log.info("No candidate cleared the bar (best %.1f) — clean exit", best)
            if not dry_run:
                notify.no_video_today(best)
            return
        best = ranked[0]
        log.info("Selected [%.1f]: %s", best["score"], best["hook"])

        stage = "evidence"
        snippets = evidence.gather(best)

        stage = "script"
        script = script_mod.write_script(best, snippets)
        (out_dir / "script.json").write_text(
            json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        stage = "tts"
        narration, words, beat_ends = tts.narrate(script["beats"], out_dir)

        stage = "captions"
        ass_file = captions.build_ass(words, out_dir)

        stage = "visuals"
        title_card = visuals.make_title_card(script["belief"], out_dir)
        verdict_card = visuals.make_verdict_card(script["verdict"], out_dir)
        clips = visuals.fetch_clips([b["visual_keyword"] for b in script["beats"]], out_dir)

        stage = "assemble"
        video = assemble.assemble(
            out_dir, title_card, verdict_card, clips, beat_ends, narration, ass_file
        )

        if dry_run:
            log.info("Dry run complete: %s", video)
            return

        stage = "upload"
        description = script_mod.full_description(script)
        video_id = youtube.upload(video, script["title"], description, script["tags"])

        stage = "state"
        hypothesis.save_to_history(
            {
                "date": datetime.date.today().isoformat(),
                "belief": script["belief"],
                "title": script["title"],
                "verdict": script["verdict"],
                "video_id": video_id,
                "score": best["score"],
            }
        )

        notify.video_ready(script["title"], video_id)
        log.info("Done: https://youtu.be/%s", video_id)

    except Exception as exc:
        log.exception("Pipeline failed at stage '%s'", stage)
        if not dry_run:
            notify.pipeline_failed(stage, str(exc))
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="produce the video locally but skip upload/history/notify")
    run(dry_run=parser.parse_args().dry_run)
