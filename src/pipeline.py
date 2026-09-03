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

from src import analytics, config
from src.generate import evidence, hypothesis, script as script_mod
from src.media import assemble, captions, tts, visuals
from src.publish import instagram, notify, youtube
from src.sources import reddit

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pipeline")

ENGAGE_COMMENT = "What do you think — does this change how you see it? 👇"


def _post_pending_comments() -> None:
    """Post the engagement comment on videos that have since gone public.
    Comments can't be added while a video is private, so this runs each day."""
    history = hypothesis.load_history()
    changed = False
    for entry in history:
        if entry.get("commented") or not entry.get("video_id"):
            continue
        try:
            if youtube.is_public(entry["video_id"]):
                youtube.post_comment(entry["video_id"], ENGAGE_COMMENT)
                entry["commented"] = True
                changed = True
        except Exception as exc:
            log.warning("Comment sweep failed for %s: %s", entry["video_id"], exc)
    if changed:
        config.STATE_FILE.write_text(
            json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def run(dry_run: bool = False, scheduled: bool = False) -> None:
    stage = "init"
    try:
        # Scheduled runs fire multiple times/day (fallback crons for reliability)
        # but should yield only ONE video — skip if today already produced one.
        # Manual dispatch ignores this guard, so the user can still make extras.
        if scheduled:
            today = datetime.date.today().isoformat()
            if any(h.get("date") == today for h in hypothesis.load_history()):
                log.info("A video was already produced today (%s) — scheduled run exits", today)
                return

        # timestamped run dir — multiple runs per day must not overwrite each other
        out_dir = config.OUT_DIR / datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        out_dir.mkdir(parents=True, exist_ok=True)

        # startup maintenance (real runs only): keep IG token alive, post
        # engagement comments on now-public videos, refresh stats for scoring.
        calibration = ""
        if not dry_run:
            stage = "maintenance"
            instagram.refresh_token()
            _post_pending_comments()
            analytics.refresh_stats()
            calibration = analytics.calibration_block()

        stage = "source"
        threads = reddit.fetch_all_threads()
        if not threads:
            raise RuntimeError("No source threads fetched")
        log.info("Fetched %d threads", len(threads))

        stage = "hypothesize"
        candidates = hypothesis.generate_candidates(threads)
        ranked = hypothesis.score_candidates(candidates, calibration=calibration)
        if not ranked or ranked[0]["score"] < config.MIN_SCORE_TO_PROCEED:
            best = ranked[0]["score"] if ranked else 0.0
            log.info("No candidate cleared the bar (best %.1f) — clean exit", best)
            if not dry_run:
                notify.no_video_today(best)
            return
        # Gather evidence for the top candidates and rank them by how well the
        # evidence SUPPORTS the claim (0-10), not a pass/fail veto. We publish
        # the best-supported candidate of the day; only claims the evidence
        # actively contradicts (score < MIN_SUPPORT_SCORE) are dropped. A
        # strongly-supported candidate short-circuits the search.
        # The day already cleared the quality bar (ranked[0] >= MIN_SCORE above).
        # Now evaluate the top ideas by support regardless of each one's own
        # score — a well-sourced 5.5 beats a 7.0 that turns out to be a myth or
        # a duplicate. Score picks the pool; evidence picks the winner.
        stage = "evidence"
        scored: list[tuple[float, dict, list[dict], str]] = []
        for candidate in ranked[: config.EVIDENCE_CANDIDATE_LIMIT]:
            log.info("Trying [%.1f]: %s", candidate["score"], candidate["hook"])
            stage = "dedupe"
            if hypothesis.is_duplicate(candidate):
                continue
            stage = "evidence"
            snippets = evidence.gather(candidate)
            if len(snippets) < 3:
                log.warning("Only %d evidence snippets — trying next candidate", len(snippets))
                continue
            support, reason = evidence.support_score(candidate, snippets)
            if support < config.MIN_SUPPORT_SCORE:
                log.warning("Evidence contradicts/does not cover the claim "
                            "(support %.0f, %s) — skipping", support, reason)
                continue
            scored.append((support, candidate, snippets, reason))
            if support >= config.STRONG_SUPPORT_SCORE:
                break  # well-supported enough; no need to keep searching

        # Best-supported first; scripting failures fall through to the next.
        script, best = None, None
        for support, candidate, snippets, reason in sorted(
            scored, key=lambda t: t[0], reverse=True
        ):
            log.info("Scripting best-supported [support %.0f]: %s", support, candidate["hook"])
            stage = "script"
            try:
                script = script_mod.write_script(candidate, snippets)
                best = candidate
                break
            except RuntimeError as exc:
                log.warning("Scripting failed for this candidate: %s", exc)
        if script is None:
            # Nothing survived: every top candidate was either contradicted by
            # its evidence or couldn't be scripted. A later cron retries with
            # fresh threads; alert as a quiet day, not a pipeline failure.
            log.info("No candidate had non-contradicted evidence — clean exit")
            if not dry_run:
                notify.no_video_today(
                    ranked[0]["score"], reason="no candidate's claim was backed by evidence"
                )
            return
        (out_dir / "script.json").write_text(
            json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        stage = "tts"
        narration, words, beat_ends = tts.narrate(script["beats"], out_dir)

        stage = "captions"
        ass_file = captions.build_ass(words, out_dir)

        stage = "visuals"
        title_card = visuals.make_title_card(script["belief"], out_dir)
        question_card = visuals.make_question_card(out_dir)
        # clips only for the middle beats — cards cover the intro and closer
        clips = visuals.fetch_clips(
            [b["visual_keyword"] for b in script["beats"][1:-1]], out_dir
        )

        stage = "assemble"
        video = assemble.assemble(
            out_dir, title_card, question_card, clips, beat_ends, narration, ass_file
        )

        if dry_run:
            log.info("Dry run complete: %s", video)
            return

        stage = "upload"
        description = script_mod.full_description(script)
        video_id = youtube.upload(video, script["title"], description, script["tags"])

        # Instagram cross-post — fail-soft: never roll back the YouTube upload
        stage = "instagram"
        ig_media_id = None
        try:
            ig_media_id = instagram.upload_reel(video, script_mod.caption_for_instagram(script))
        except Exception as exc:
            log.warning("Instagram cross-post failed (non-fatal): %s", exc)

        stage = "state"
        hypothesis.save_to_history(
            {
                "date": datetime.date.today().isoformat(),
                "belief": script["belief"],
                "title": script["title"],
                "video_id": video_id,
                "ig_media_id": ig_media_id,
                "commented": False,
                "score": best["score"],
            }
        )

        notify.video_ready(script["title"], video_id)
        if ig_media_id:
            log.info("Instagram Reel published: %s", ig_media_id)
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
    parser.add_argument("--scheduled", action="store_true",
                        help="cron-triggered: skip if a video was already produced today")
    args = parser.parse_args()
    run(dry_run=args.dry_run, scheduled=args.scheduled)
