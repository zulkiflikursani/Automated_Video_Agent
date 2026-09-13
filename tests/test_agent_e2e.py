"""Phase 5 verification: end-to-end pipeline dry run through the agent.

Uses a real synthetic MP4 (ffmpeg testsrc) with a mocked yt-dlp download, so
the entire scan->process->publish(dry)->GC chain runs against the real DB.
"""
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from backend import agent, models
from backend.db import engine, init_db, session_scope


# ---------- helpers ----------

@pytest.fixture(scope="module")
def synthetic_video(tmp_path_factory):
    """65s low-res 16:9 video with audio; small so FFmpeg passes stay fast."""
    out = tmp_path_factory.mktemp("e2e") / "raw.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=65:size=320x180:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=65",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest",
            str(out),
        ],
        check=True, capture_output=True,
    )
    return str(out)


@pytest.fixture()
def db():
    init_db()
    yield
    models.Base.metadata.drop_all(bind=engine)


def _fake_download(synthetic_path, downloads_dir):
    """Return a download_video replacement that 'downloads' the synthetic file."""

    def fake_download(url, video_id):
        os.makedirs(downloads_dir, exist_ok=True)
        dest = os.path.join(downloads_dir, f"{video_id}.mp4")
        shutil.copyfile(synthetic_path, dest)
        return dest

    return fake_download


# ---------- end-to-end dry run ----------

def test_full_pipeline_end_to_end(db, synthetic_video, tmp_path):
    from backend import config

    downloads = str(tmp_path / "downloads")
    with mock.patch.object(config, "DOWNLOADS_DIR", downloads), \
         mock.patch.object(config, "PROCESSED_DIR", str(tmp_path / "processed")), \
         mock.patch.object(agent.ingestion, "download_video",
                           side_effect=_fake_download(synthetic_video, downloads)):
        # 1. Register video as a source scan would
        with session_scope() as s:
            src = models.Source(name="Chan", url="https://x.com/c")
            s.add(src)
            s.flush()
            s.add(models.Video(
                source_id=src.id, source_video_id="e2e1",
                title="CEO jatuh cinta ep 1", duration=65,
                original_url="https://youtu.be/e2e1",
            ))

        # 2. Pipeline: download -> process full + clips -> enqueue
        assert agent.process_pending_videos() == 1

        with session_scope() as s:
            video = s.query(models.Video).one()
            assert video.status == "READY"
            clips = s.query(models.Clip).order_by(models.Clip.part_number).all()
            assert 1 <= len(clips) <= 5
            for i, clip in enumerate(clips, 1):
                assert clip.part_number == i and clip.status == "READY"
                assert os.path.exists(clip.local_clip_path)
            assert os.path.exists(video.local_raw_path)

            queue = s.query(models.PublishingQueue).all()
            assert len(queue) == len(clips) + 1  # full video + reels
            assert sum(1 for q in queue if q.post_type == "REGULAR_VIDEO") == 1
            assert all(q.status == "QUEUED" for q in queue)

            # 3. Force schedule into the past so everything is due now
            past = datetime.now(timezone.utc) - timedelta(minutes=1)
            for q in queue:
                q.scheduled_for = past

        # 4. Publish (dry-run) -> video PUBLISHED
        assert agent.publish_due_entries() == len(queue)

        with session_scope() as s:
            video = s.query(models.Video).one()
            assert video.status == "PUBLISHED"
            entries = s.query(models.PublishingQueue).all()
            assert all(q.status == "SUCCESS" for q in entries)
            assert all((q.fb_post_id or "").startswith("dryrun_") for q in entries)
            assert all(q.published_at is not None for q in entries)

            # 5. GC removes local media (PRD 6: zero disk bloat)
            clip_paths = [c.local_clip_path for c in video.clips]
            raw_path = video.local_raw_path

        removed = agent.run_garbage_collector()

        assert removed == len(clip_paths) + 1
        assert not os.path.exists(raw_path)
        for p in clip_paths:
            assert not os.path.exists(p)
        with session_scope() as s:
            video = s.query(models.Video).one()
            assert video.local_raw_path is None
            assert all(c.local_clip_path is None for c in video.clips)


# ---------- drip-feed caps (PRD 6: max 2 full + 4 reels per 24h) ----------

def _make_queue_entries(post_type, count, synthetic_path):
    """Seed a READY video with `count` due queue entries of the given type."""
    from backend import config as cfg

    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    with session_scope() as s:
        video = models.Video(source_video_id=f"cap_{post_type}",
                             title="T", original_url="u", status="READY")
        s.add(video)
        s.flush()
        media_dir = os.path.join(cfg.DOWNLOADS_DIR, "cap")
        os.makedirs(media_dir, exist_ok=True)
        media = os.path.join(media_dir, f"{post_type}.mp4")
        shutil.copyfile(synthetic_path, media)
        video.local_raw_path = media
        for i in range(count):
            s.add(models.PublishingQueue(
                video_id=video.id, post_type=post_type,
                scheduled_for=past, clip_id=None,
            ))
    return video.id


def test_drip_feed_cap_limits_full_videos(db, synthetic_video):
    video_id = _make_queue_entries("REGULAR_VIDEO", 2, synthetic_video)

    # Lower the cap to 1 full video per day
    with session_scope() as s:
        row = s.get(models.SystemSetting, "drip_feed_full_per_day")
        row.value = "1"

    published = agent.publish_due_entries()

    assert published == 1
    with session_scope() as s:
        statuses = [q.status for q in
                    s.query(models.PublishingQueue).filter_by(video_id=video_id).all()]
        assert sorted(statuses) == ["QUEUED", "SUCCESS"]


# ---------- retry & failure path ----------

def test_publish_retry_then_permanent_failure(db):
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    with session_scope() as s:
        video = models.Video(source_video_id="retry1", title="T",
                             original_url="u", status="READY")
        s.add(video)
        s.flush()
        s.add(models.PublishingQueue(
            video_id=video.id, post_type="REGULAR_VIDEO", scheduled_for=past,
        ))

    with mock.patch.object(agent.publisher, "upload_full_video",
                           side_effect=RuntimeError("fb down")):
        # MAX_RETRIES attempts; each failure requeues with +30min except the last
        for expected_retries in range(1, agent.config.MAX_RETRIES):
            with session_scope() as s:
                entry = s.query(models.PublishingQueue).one()
                entry.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
            assert agent.publish_due_entries() == 0
            with session_scope() as s:
                entry = s.query(models.PublishingQueue).one()
                assert entry.status == "QUEUED"
                assert entry.retry_count == expected_retries

        # final allowed attempt -> FAILED
        with session_scope() as s:
            entry = s.query(models.PublishingQueue).one()
            entry.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert agent.publish_due_entries() == 0
        with session_scope() as s:
            entry = s.query(models.PublishingQueue).one()
            assert entry.status == "FAILED"
            assert entry.retry_count == agent.config.MAX_RETRIES
            assert "fb down" in entry.logs
