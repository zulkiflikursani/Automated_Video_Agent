"""Phase 6 verification: REST API endpoints for the dashboard."""
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from backend import agent, models
from backend.api import app
from backend.db import engine, init_db, session_scope


@pytest.fixture()
def client():
    init_db()
    with TestClient(app) as c:
        yield c
    models.Base.metadata.drop_all(bind=engine)


def test_health(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["dry_run"] is True


def test_metrics_empty(client):
    body = client.get("/api/metrics").json()
    assert body["total_videos"] == 0
    assert body["reels_cut"] == 0
    assert body["success_rate"] is None


def test_sources_crud(client):
    created = client.post("/api/sources", json={"name": "Chan", "url": "https://x.com/c"}).json()
    assert created["id"] > 0

    # duplicate URL rejected
    assert client.post("/api/sources", json={"name": "X", "url": "https://x.com/c"}).status_code == 409

    assert len(client.get("/api/sources").json()) == 1

    patched = client.patch(f"/api/sources/{created['id']}", json={"is_active": False}).json()
    assert patched["is_active"] is False

    assert client.delete(f"/api/sources/{created['id']}").status_code == 204
    assert client.get("/api/sources").json() == []


def test_videos_and_clips_listing(client):
    with session_scope() as s:
        video = models.Video(source_video_id="v1", title="Ep 1", original_url="u", status="READY")
        s.add(video)
        s.flush()
        s.add(models.Clip(video_id=video.id, part_number=1, start_time_sec=60,
                          end_time_sec=100, duration=40, overlay_title="Ep 1", status="READY"))

    videos = client.get("/api/videos").json()
    assert videos[0]["title"] == "Ep 1"
    assert videos[0]["clips"][0]["part_number"] == 1

    clips = client.get("/api/clips").json()
    assert clips[0]["video_title"] == "Ep 1"


def test_queue_reschedule_and_delete(client):
    with session_scope() as s:
        video = models.Video(source_video_id="q1", title="T", original_url="u", status="READY")
        s.add(video)
        s.flush()
        s.add(models.PublishingQueue(
            video_id=video.id, post_type="REGULAR_VIDEO",
            scheduled_for=datetime.now(timezone.utc) + timedelta(hours=2),
        ))

    entry = client.get("/api/queue").json()[0]
    assert entry["status"] == "QUEUED"

    new_time = "2026-12-01T10:00:00+00:00"
    patched = client.patch(f"/api/queue/{entry['id']}", json={"scheduled_for": new_time}).json()
    assert patched["scheduled_for"].startswith("2026-12-01T10:00:00")

    # failed entry rescheduled back to QUEUED
    with session_scope() as s:
        row = s.get(models.PublishingQueue, entry["id"])
        row.status = "FAILED"
    patched = client.patch(f"/api/queue/{entry['id']}", json={"scheduled_for": new_time}).json()
    assert patched["status"] == "QUEUED"

    assert client.delete(f"/api/queue/{entry['id']}").status_code == 204
    assert client.get("/api/queue").json() == []


def test_publish_now_triggers_cycle(client):
    with session_scope() as s:
        video = models.Video(source_video_id="pn1", title="T", original_url="u", status="READY")
        s.add(video)
        s.flush()
        s.add(models.PublishingQueue(
            video_id=video.id, post_type="REGULAR_VIDEO",
            scheduled_for=datetime.now(timezone.utc) + timedelta(hours=5),
        ))
    entry_id = client.get("/api/queue").json()[0]["id"]

    with mock.patch.object(agent, "publish_due_entries", return_value=1):
        body = client.post(f"/api/queue/{entry_id}/publish-now").json()
    assert body["cycle_published"] == 1
    assert body["status"] in ("QUEUED", "SUCCESS")


def test_settings_mask_and_update(client):
    with session_scope() as s:
        row = s.get(models.SystemSetting, "fb_page_access_token")
        row.value = "EAAG-secret-token-123"

    settings = {s["key"]: s["value"] for s in client.get("/api/settings").json()}
    assert settings["fb_page_access_token"].startswith("EAAG-")
    assert settings["fb_page_access_token"].endswith("***")
    assert "secret" not in settings["fb_page_access_token"]
    assert settings["dry_run"] in ("true", "false")

    resp = client.patch("/api/settings/dry_run", json={"value": "false"})
    assert resp.json()["updated"] is True
    with session_scope() as s:
        assert s.get(models.SystemSetting, "dry_run").value == "false"


def test_logs_feed(client):
    with session_scope() as s:
        video = models.Video(source_video_id="lg1", title="T", original_url="u", status="READY")
        s.add(video)
        s.flush()
        s.add(models.PublishingQueue(
            video_id=video.id, post_type="REELS",
            scheduled_for=datetime.now(timezone.utc) - timedelta(hours=1),
            status="SUCCESS", fb_post_id="dryrun_reel_abc",
            published_at=datetime.now(timezone.utc),
        ))
    feed = client.get("/api/logs").json()
    assert any(f["level"] == "SUCCESS" and "dryrun_reel_abc" in f["message"] for f in feed)


def test_run_cycle_endpoint(client):
    with mock.patch.object(agent, "run_all_once", return_value={}) as run_all:
        resp = client.post("/api/run-cycle")
    assert resp.json()["started"] is True
    run_all.assert_called_once()
