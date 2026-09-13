"""Source scanning job: register newly discovered videos as PENDING."""
import logging
from datetime import datetime, timedelta, timezone

from backend import models
from backend.db import session_scope
from backend.modules import ingestion

logger = logging.getLogger(__name__)


def due_sources(db):
    """Active sources whose check_interval_hours have elapsed since last check."""
    now = datetime.now(timezone.utc)
    due = []
    for source in db.query(models.Source).filter_by(is_active=True).all():
        if source.last_checked_at is None:
            due.append(source)
            continue
        last = source.last_checked_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now - last >= timedelta(hours=source.check_interval_hours):
            due.append(source)
    return due


def scan_sources() -> int:
    """Scan all due sources; return the number of newly registered videos."""
    new_count = 0
    with session_scope() as db:
        for source in due_sources(db):
            logger.info("Scanning source %s (%s)", source.name, source.url)
            try:
                entries = ingestion.list_source_videos(source.url)
            except Exception as exc:  # noqa: BLE001 - keep scanning other sources
                logger.error("Source scan failed for %s: %s", source.name, exc)
                source.last_checked_at = datetime.now(timezone.utc)
                continue

            known_ids = {row[0] for row in db.query(models.Video.source_video_id).all()}
            for entry in entries:
                if entry["id"] in known_ids:
                    continue
                db.add(
                    models.Video(
                        source_id=source.id,
                        source_video_id=entry["id"],
                        title=(entry["title"] or "Untitled")[:500],
                        duration=entry["duration"],
                        original_url=entry["url"],
                    )
                )
                known_ids.add(entry["id"])
                new_count += 1
            source.last_checked_at = datetime.now(timezone.utc)
    logger.info("Scan complete: %d new video(s) registered", new_count)
    return new_count
