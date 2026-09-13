"""Agent orchestration: pipeline worker, publishing worker, garbage collector.

Flow (PRD section 2):
    scan -> videos(PENDING) -> pipeline: download -> plan clips -> process
         -> queue(REGULAR_VIDEO + REELS) -> publish (drip feed) -> GC cleanup
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend import config, models
from backend.db import session_scope
from backend.jobs import scan_sources
from backend.modules import clip_planner, ingestion, processor, publisher
from backend.modules.alerter import send_alert

logger = logging.getLogger(__name__)

PUBLISH_NOW_OFFSET_MIN = 30
REELS_BASE_DELAY_HOURS = 1.0
REELS_SPACING_HOURS = 2.5


# ---------- pipeline worker ----------

def _enqueue_outputs(db: Session, video: models.Video, full_path: str, clips: list) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        models.PublishingQueue(
            video_id=video.id,
            post_type="REGULAR_VIDEO",
            scheduled_for=now + timedelta(minutes=PUBLISH_NOW_OFFSET_MIN),
        )
    )
    for clip in clips:
        db.add(
            models.PublishingQueue(
                video_id=video.id,
                clip_id=clip.id,
                post_type="REELS",
                scheduled_for=now + timedelta(hours=REELS_BASE_DELAY_HOURS)
                + timedelta(hours=REELS_SPACING_HOURS * (clip.part_number - 1)),
            )
        )


def process_pending_videos() -> int:
    """Download + process every PENDING video; returns count processed."""
    processed = 0
    with session_scope() as db:
        pending_ids = [
            row[0]
            for row in db.query(models.Video.id)
            .filter(models.Video.status == "PENDING")
            .order_by(models.Video.created_at)
            .all()
        ]
        for video_id in pending_ids:
            if _process_one(db, video_id):
                processed += 1
    if processed:
        logger.info("Pipeline processed %d video(s)", processed)
    return processed


def _process_one(db: Session, video_id: int) -> bool:
    video = db.get(models.Video, video_id)
    if video is None:
        return False
    logger.info("Processing video %s: %s", video.source_video_id, video.title)
    try:
        video.status = "DOWNLOADING"
        db.flush()

        raw_path = ingestion.download_video(video.original_url, video.source_video_id)
        video.local_raw_path = raw_path

        video.status = "PROCESSING"
        db.flush()

        os.makedirs(config.PROCESSED_DIR, exist_ok=True)
        full_out = os.path.join(config.PROCESSED_DIR, f"{video.source_video_id}_full.mp4")
        processor.process_full_video(raw_path, full_out)

        planned = clip_planner.plan_clips(video.duration or 0)
        for spec in planned:
            clip = models.Clip(
                video_id=video.id,
                part_number=spec["part_number"],
                start_time_sec=spec["start_time_sec"],
                end_time_sec=spec["end_time_sec"],
                duration=spec["duration"],
                overlay_title=(video.title or "Untitled")[:255],
                status="PROCESSING",
            )
            db.add(clip)
            db.flush()

            clip_out = os.path.join(
                config.PROCESSED_DIR,
                f"{video.source_video_id}_part{spec['part_number']}.mp4",
            )
            processor.generate_reels_clip(
                raw_path, clip_out,
                start_sec=spec["start_time_sec"],
                duration_sec=spec["duration"],
                part_num=spec["part_number"],
                title_text=(video.title or "Untitled"),
            )
            clip.local_clip_path = clip_out
            clip.status = "READY"
            db.flush()

        clips = (
            db.query(models.Clip)
            .filter(models.Clip.video_id == video.id)
            .order_by(models.Clip.part_number)
            .all()
        )
        _enqueue_outputs(db, video, full_out, clips)
        video.status = "READY"
        db.flush()
        logger.info("Video %s READY: full + %d clip(s) queued", video.source_video_id, len(clips))
        return True
    except Exception as exc:  # noqa: BLE001 - one bad video must not stop the batch
        db.rollback()
        with session_scope() as fixup:
            failed = fixup.get(models.Video, video_id)
            if failed is not None:
                failed.status = "FAILED"
                failed.error_message = str(exc)[:2000]
        logger.exception("Processing failed for video %s", video_id)
        send_alert(f"Processing FAILED for video {video_id}: {str(exc)[:200]}")
        return False


# ---------- publishing worker ----------

def _published_in_last_24h(db: Session, post_type: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    return (
        db.query(models.PublishingQueue)
        .filter(
            models.PublishingQueue.post_type == post_type,
            models.PublishingQueue.status == "SUCCESS",
            models.PublishingQueue.published_at >= since,
        )
        .count()
    )


def publish_due_entries() -> int:
    """Publish QUEUED entries that are due, respecting drip-feed caps (PRD 6)."""
    published = 0
    with session_scope() as db:
        now = datetime.now(timezone.utc)
        due = (
            db.query(models.PublishingQueue)
            .filter(
                models.PublishingQueue.status == "QUEUED",
                models.PublishingQueue.scheduled_for <= now,
            )
            .order_by(models.PublishingQueue.scheduled_for)
            .all()
        )
        caps = {
            "REGULAR_VIDEO": _setting_int(db, "drip_feed_full_per_day", config.DRIP_FEED_FULL_PER_DAY),
            "REELS": _setting_int(db, "drip_feed_reels_per_day", config.DRIP_FEED_REELS_PER_DAY),
        }
        for entry in due:
            cap = caps[entry.post_type]
            if _published_in_last_24h(db, entry.post_type) >= cap:
                continue  # cap reached; stays QUEUED for the next window
            if _publish_entry(db, entry):
                published += 1
    if published:
        logger.info("Published %d queue entry(ies)", published)
    return published


def _setting_int(db: Session, key: str, default: int) -> int:
    row = db.get(models.SystemSetting, key)
    try:
        return int(row.value) if row else default
    except (TypeError, ValueError):
        return default


def _publish_entry(db: Session, entry: models.PublishingQueue) -> bool:
    entry.status = "UPLOADING"
    db.flush()
    video = db.get(models.Video, entry.video_id)
    try:
        page_id = _setting_str(db, "fb_page_id", config.FB_PAGE_ID)
        token = _setting_str(db, "fb_page_access_token", config.FB_PAGE_ACCESS_TOKEN)

        if entry.post_type == "REGULAR_VIDEO":
            result = publisher.upload_full_video(
                page_id, token, video.local_raw_path or "",
                title=video.title, description=video.description or "",
            )
        else:
            clip = db.get(models.Clip, entry.clip_id)
            result = publisher.upload_reels_video(
                page_id, token, clip.local_clip_path or "",
                caption=f"{video.title} - Part {clip.part_number}",
            )

        entry.status = "SUCCESS"
        entry.fb_post_id = str(result.get("post_id") or result.get("success") or "")
        entry.published_at = datetime.now(timezone.utc)
        entry.logs = f"Published at {entry.published_at.isoformat()}"
        if entry.post_type == "REELS" and entry.clip_id:
            clip = db.get(models.Clip, entry.clip_id)
            if clip is not None:
                clip.status = "PUBLISHED"
        db.flush()
        _maybe_mark_video_published(db, entry.video_id)
        return True
    except Exception as exc:  # noqa: BLE001
        entry.retry_count = (entry.retry_count or 0) + 1
        entry.logs = f"Attempt {entry.retry_count}: {str(exc)[:1500]}"
        if entry.retry_count >= config.MAX_RETRIES:
            entry.status = "FAILED"
            send_alert(
                f"Publishing FAILED permanently for queue #{entry.id} "
                f"({entry.post_type}): {str(exc)[:200]}"
            )
        else:
            entry.status = "QUEUED"
            entry.scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=30)
        db.flush()
        logger.error("Publish failed for queue #%s: %s", entry.id, exc)
        return False


def _setting_str(db: Session, key: str, default: str) -> str:
    row = db.get(models.SystemSetting, key)
    return row.value if row and row.value else default


def _maybe_mark_video_published(db: Session, video_id: int) -> None:
    remaining = (
        db.query(models.PublishingQueue)
        .filter(
            models.PublishingQueue.video_id == video_id,
            models.PublishingQueue.status != "SUCCESS",
        )
        .count()
    )
    if remaining == 0:
        video = db.get(models.Video, video_id)
        if video is not None:
            video.status = "PUBLISHED"


# ---------- garbage collector ----------

def run_garbage_collector() -> int:
    """Delete local media after SUCCESS (PRD 6: zero disk bloat). Returns files removed."""
    removed = 0
    with session_scope() as db:
        published_videos = (
            db.query(models.Video)
            .filter(models.Video.status == "PUBLISHED", models.Video.local_raw_path.isnot(None))
            .all()
        )
        for video in published_videos:
            removed += _remove_file(video.local_raw_path)
            video.local_raw_path = None

        published_clips = (
            db.query(models.Clip)
            .filter(models.Clip.status == "PUBLISHED", models.Clip.local_clip_path.isnot(None))
            .all()
        )
        for clip in published_clips:
            removed += _remove_file(clip.local_clip_path)
            clip.local_clip_path = None
    if removed:
        logger.info("GC removed %d file(s)", removed)
    return removed


def _remove_file(path) -> int:
    if not path:
        return 0
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info("GC removed %s", path)
            return 1
    except OSError as exc:
        logger.error("GC could not remove %s: %s", path, exc)
    return 0


# ---------- convenience entry points ----------

def run_scan() -> int:
    return scan_sources.scan_sources()


def run_all_once() -> dict:
    """One full manual cycle: scan -> pipeline -> publish -> gc."""
    return {
        "new_videos": run_scan(),
        "processed": process_pending_videos(),
        "published": publish_due_entries(),
        "gc_files_removed": run_garbage_collector(),
    }
