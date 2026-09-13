"""Tests: Discover panel (keyword search -> pipeline) + live progress feed."""
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from backend import api as api_module
from backend import models
from backend.api import app
from backend.db import engine, init_db, session_scope
from backend.modules import keywords
from backend import monitor


@pytest.fixture()
def client():
    init_db()
    with TestClient(app) as c:
        yield c
    models.Base.metadata.drop_all(bind=engine)


# ---------- keyword templates ----------

def test_keyword_groups_present():
    assert "Trending Harian (ID)" in keywords.KEYWORD_GROUPS
    assert all(len(tmpls) >= 3 for tmpls in keywords.KEYWORD_GROUPS.values())


def test_keyword_expand_and_validate():
    assert keywords.expand("drama cina sub indo {n}", 15) == "drama cina sub indo 15"
    assert keywords.validate("") is not None
    assert keywords.validate("x" * 200) is not None
    assert keywords.validate("drama cina 2026") is None


# ---------- /api/keywords ----------

def test_keywords_endpoint(client):
    body = client.get("/api/keywords").json()
    assert body["default"].endswith("{n}")
    assert "Mini Drama Viral" in body["groups"]


# ---------- /api/discover ----------

def test_discover_search_mocked(client):
    fake = [
        {"id": "abc", "title": "Drama Viral", "channel": "Ch", "duration": 1200,
         "views": 50000, "url": "https://youtu.be/abc"},
    ]
    with mock.patch.object(api_module.ingestion_mod, "search_youtube", return_value=fake):
        body = client.post("/api/discover", json={"keyword": "drama cina {n}", "limit": 5}).json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == "abc"


def test_discover_rejects_empty_keyword(client):
    assert client.post("/api/discover", json={"keyword": "   "}).status_code == 422


def test_discover_surfaces_search_failure(client):
    with mock.patch.object(api_module.ingestion_mod, "search_youtube",
                           side_effect=RuntimeError("yt-dlp down")):
        assert client.post("/api/discover", json={"keyword": "drama"}).status_code == 502


# ---------- /api/discover/add ----------

def test_discover_add_creates_pending_video(client):
    body = client.post("/api/discover/add", json={
        "video_id": "new1", "title": "Trending Drama", "url": "https://youtu.be/new1",
        "duration": 900,
    }).json()
    assert body["status"] == "PENDING"
    # duplicate rejected
    dup = client.post("/api/discover/add", json={
        "video_id": "new1", "title": "Trending Drama", "url": "https://youtu.be/new1",
    })
    assert dup.status_code == 409


# ---------- /api/progress ----------

def test_monitor_event_writes_row():
    init_db()
    monitor.event("download", "vid1", "Some Drama", 42, "downloading")
    with session_scope() as db:
        row = (
            db.query(models.JobEvent)
            .filter_by(video_ref="vid1", stage="download")
            .order_by(models.JobEvent.id.desc())
            .first()
        )
        assert row is not None
        assert row.percent == 42


def test_progress_endpoint_returns_events(client):
    monitor.event("upload", "vid2", "Drama X", 75, "uploading to page")
    monitor.event("publish", "vid2", "Drama X", 100, "published")
    body = client.get("/api/progress").json()
    stages = [e["stage"] for e in body]
    assert "upload" in stages and "publish" in stages
    newest = body[0]
    assert set(newest.keys()) >= {"stage", "video_ref", "title", "percent", "created_at"}
