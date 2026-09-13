"""Phase 1 verification: DB layer behaviors from PRD section 3."""
import pytest

from backend import models
from backend.db import init_db, session_scope


@pytest.fixture()
def db():
    init_db()
    with session_scope() as session:
        try:
            yield session
        finally:
            session.rollback()
            models.Base.metadata.drop_all(bind=session.get_bind())


def test_all_five_tables_created(db):
    tables = set(models.Base.metadata.tables.keys())
    assert tables == {"sources", "videos", "clips", "publishing_queue", "system_settings"}


def test_source_and_video_crud(db):
    src = models.Source(name="Test Channel", url="https://youtube.com/@test")
    db.add(src)
    db.flush()

    vid = models.Video(
        source_id=src.id,
        source_video_id="yt_abc123",
        title="CEO jatuh cinta ep 1",
        duration=1200,
        original_url="https://youtube.com/watch?v=abc123",
    )
    db.add(vid)
    db.flush()

    fetched = db.query(models.Video).filter_by(source_video_id="yt_abc123").one()
    assert fetched.status == "PENDING"
    assert fetched.source.name == "Test Channel"


def test_duplicate_source_video_id_rejected(db):
    db.add(
        models.Video(
            source_video_id="dup1", title="A", original_url="u1"
        )
    )
    db.flush()
    db.add(
        models.Video(
            source_video_id="dup1", title="B", original_url="u2"
        )
    )
    with pytest.raises(Exception):
        db.flush()
    db.rollback()


def test_duplicate_source_url_rejected(db):
    db.add(models.Source(name="A", url="https://x.com/1"))
    db.flush()
    db.add(models.Source(name="B", url="https://x.com/1"))
    with pytest.raises(Exception):
        db.flush()
    db.rollback()


def test_cascade_delete_video_removes_clips_and_queue(db):
    vid = models.Video(source_video_id="v1", title="T", original_url="u")
    db.add(vid)
    db.flush()

    clip = models.Clip(
        video_id=vid.id, part_number=1, start_time_sec=0, end_time_sec=45, duration=45
    )
    db.add(clip)
    db.flush()

    db.add(
        models.PublishingQueue(
            video_id=vid.id, clip_id=clip.id, post_type="REELS", scheduled_for=utcnow_plus(1)
        )
    )
    db.add(
        models.PublishingQueue(
            video_id=vid.id, post_type="REGULAR_VIDEO", scheduled_for=utcnow_plus(2)
        )
    )
    db.flush()

    db.delete(vid)
    db.flush()

    assert db.query(models.Clip).count() == 0
    assert db.query(models.PublishingQueue).count() == 0


def test_delete_source_nullifies_video_source(db):
    src = models.Source(name="Gone", url="https://x.com/gone")
    db.add(src)
    db.flush()
    vid = models.Video(
        source_id=src.id, source_video_id="s1", title="T", original_url="u"
    )
    db.add(vid)
    db.flush()

    db.delete(src)
    db.flush()
    db.refresh(vid)

    assert vid.source_id is None


def test_system_settings_seeded(db):
    keys = {s.key for s in db.query(models.SystemSetting).all()}
    assert {"fb_page_id", "drip_feed_full_per_day", "dry_run", "watermark_text"} <= keys


def utcnow_plus(hours):
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) + timedelta(hours=hours)
