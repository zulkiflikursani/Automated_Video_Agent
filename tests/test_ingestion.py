"""Phase 2 verification: ingestion module and source scanning (mocked yt-dlp)."""
from unittest import mock

import pytest

from backend import models
from backend.db import init_db, session_scope
from backend.jobs import scan_sources
from backend.modules import ingestion


@pytest.fixture()
def db():
    init_db()
    with session_scope() as session:
        try:
            yield session
        finally:
            session.rollback()
            models.Base.metadata.drop_all(bind=session.get_bind())


def test_list_source_videos_flattens_entries():
    fake_info = {
        "entries": [
            {"id": "abc", "title": "Ep 1", "url": "https://youtu.be/abc", "duration": 900},
            None,  # yt-dlp can yield None entries for deleted videos
            {"id": "def", "title": None, "url": "https://youtu.be/def", "duration": None},
        ]
    }
    with mock.patch.object(ingestion.yt_dlp, "YoutubeDL") as ydl_cls:
        ydl_cls.return_value.__enter__.return_value.extract_info.return_value = fake_info
        entries = ingestion.list_source_videos("https://youtube.com/@channel")

    assert [e["id"] for e in entries] == ["abc", "def"]
    assert entries[0]["title"] == "Ep 1"
    assert entries[1]["title"] == "Untitled"


def test_download_video_returns_existing_path(tmp_path):
    with mock.patch.object(ingestion.yt_dlp, "YoutubeDL") as ydl_cls:
        ydl = ydl_cls.return_value.__enter__.return_value
        ydl.extract_info.return_value = {"id": "abc123"}
        ydl.prepare_filename.return_value = str(tmp_path / "abc123.mp4")
        (tmp_path / "abc123.mp4").write_bytes(b"fake video bytes")

        path = ingestion.download_video("https://youtu.be/abc123", "abc123")

    assert path.endswith("abc123.mp4")


def test_download_video_raises_if_file_missing(tmp_path):
    with mock.patch.object(ingestion.yt_dlp, "YoutubeDL") as ydl_cls:
        ydl = ydl_cls.return_value.__enter__.return_value
        ydl.extract_info.return_value = {"id": "gone"}
        ydl.prepare_filename.return_value = str(tmp_path / "gone.mp4")

        with pytest.raises(FileNotFoundError):
            ingestion.download_video("https://youtu.be/gone", "gone")


def test_scan_sources_registers_new_videos_once(db):
    db.add(models.Source(name="Chan", url="https://youtube.com/@chan"))
    db.commit()

    fake_entries = [
        {"id": "v1", "title": "Ep 1", "url": "https://youtu.be/v1", "duration": 800},
        {"id": "v2", "title": "Ep 2", "url": "https://youtu.be/v2", "duration": 810},
    ]
    with mock.patch.object(ingestion, "list_source_videos", return_value=fake_entries):
        assert scan_sources.scan_sources() == 2
        assert scan_sources.scan_sources() == 0  # second run: nothing new

    titles = [v.title for v in db.query(models.Video).order_by(models.Video.source_video_id)]
    assert titles == ["Ep 1", "Ep 2"]

    source = db.query(models.Source).one()
    assert source.last_checked_at is not None


def test_scan_sources_skips_inactive_and_respects_interval(db):
    from datetime import datetime, timedelta, timezone

    db.add(
        models.Source(
            name="Inactive", url="https://x.com/off", is_active=False
        )
    )
    recent = models.Source(
        name="Fresh",
        url="https://x.com/fresh",
        last_checked_at=datetime.now(timezone.utc) - timedelta(hours=1),
        check_interval_hours=6,
    )
    db.add(recent)
    db.flush()

    with mock.patch.object(ingestion, "list_source_videos") as listing:
        assert scan_sources.scan_sources() == 0
        listing.assert_not_called()
