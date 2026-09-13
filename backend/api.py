"""FastAPI REST API powering the Web Control Dashboard (PRD section 5).

Run: .venv/bin/uvicorn backend.api:app --port 8000
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import agent, config, models
from backend.db import get_db, init_db, session_scope
from backend.modules import keywords
from backend.modules import ingestion as ingestion_mod

logger = logging.getLogger(__name__)

app = FastAPI(title="FB Video Auto-Agent API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------- schemas ----------

class SourceIn(BaseModel):
    name: str
    url: str
    platform: str = "youtube"
    check_interval_hours: int = 6


class SourcePatch(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    check_interval_hours: Optional[int] = None


class QueuePatch(BaseModel):
    scheduled_for: Optional[datetime] = None


class SettingsPatch(BaseModel):
    value: str


class DiscoverIn(BaseModel):
    keyword: str
    limit: int = 10


class DiscoverAddIn(BaseModel):
    video_id: str
    title: str
    url: str
    duration: Optional[int] = None


# ---------- health & metrics ----------

@app.get("/api/health")
def health():
    return {"ok": True, "dry_run": config.DRY_RUN}


@app.get("/api/metrics")
def metrics(db: Session = Depends(get_db)):
    total_videos = db.query(models.Video).count()
    reels_cut = db.query(models.Clip).count()
    queue_entries = db.query(models.PublishingQueue).all()
    terminal = [q for q in queue_entries if q.status in ("SUCCESS", "FAILED")]
    success_rate = (
        round(100 * sum(1 for q in terminal if q.status == "SUCCESS") / len(terminal))
        if terminal else None
    )
    return {
        "total_videos": total_videos,
        "reels_cut": reels_cut,
        "success_rate": success_rate,
        "queued": sum(1 for q in queue_entries if q.status == "QUEUED"),
        "published": sum(1 for q in queue_entries if q.status == "SUCCESS"),
        "failed": sum(1 for q in queue_entries if q.status == "FAILED"),
        "videos_failed": db.query(models.Video).filter_by(status="FAILED").count(),
        "dry_run": config.DRY_RUN,
    }


# ---------- sources (PRD 5.2: Source Management Panel) ----------

@app.get("/api/sources")
def list_sources(db: Session = Depends(get_db)):
    sources = db.query(models.Source).order_by(models.Source.id).all()
    return [
        {
            "id": s.id, "name": s.name, "url": s.url, "platform": s.platform,
            "is_active": s.is_active, "check_interval_hours": s.check_interval_hours,
            "last_checked_at": _iso(s.last_checked_at),
            "video_count": db.query(models.Video).filter_by(source_id=s.id).count(),
        }
        for s in sources
    ]


@app.post("/api/sources", status_code=201)
def create_source(payload: SourceIn, db: Session = Depends(get_db)):
    if db.query(models.Source).filter_by(url=payload.url).first():
        raise HTTPException(409, "Source URL already exists")
    source = models.Source(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return {"id": source.id, "name": source.name, "url": source.url}


@app.patch("/api/sources/{source_id}")
def patch_source(source_id: int, payload: SourcePatch, db: Session = Depends(get_db)):
    source = db.get(models.Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    db.commit()
    return {"id": source.id, "is_active": source.is_active}


@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(models.Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    db.delete(source)
    db.commit()


# ---------- videos & clips ----------

@app.get("/api/videos")
def list_videos(db: Session = Depends(get_db)):
    videos = db.query(models.Video).order_by(models.Video.created_at.desc()).limit(200).all()
    return [_video_dict(v) for v in videos]


@app.get("/api/clips")
def list_clips(video_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(models.Clip).order_by(models.Clip.video_id, models.Clip.part_number)
    if video_id:
        query = query.filter(models.Clip.video_id == video_id)
    return [
        {
            "id": c.id, "video_id": c.video_id, "part_number": c.part_number,
            "start_time_sec": c.start_time_sec, "end_time_sec": c.end_time_sec,
            "duration": c.duration, "overlay_title": c.overlay_title,
            "status": c.status,
            "video_title": c.video.title if c.video else None,
        }
        for c in query.limit(500).all()
    ]


# ---------- publishing queue (PRD 5.2: Interactive Queue Override) ----------

@app.get("/api/queue")
def list_queue(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.PublishingQueue).order_by(models.PublishingQueue.scheduled_for)
    if status:
        query = query.filter(models.PublishingQueue.status == status)
    entries = query.limit(300).all()
    return [_queue_dict(db, e) for e in entries]


@app.patch("/api/queue/{entry_id}")
def reschedule(entry_id: int, payload: QueuePatch, db: Session = Depends(get_db)):
    entry = db.get(models.PublishingQueue, entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    entry.scheduled_for = payload.scheduled_for
    if entry.status == "FAILED":
        entry.status = "QUEUED"
    db.commit()
    return _queue_dict(db, entry)


@app.post("/api/queue/{entry_id}/publish-now")
def publish_now(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(models.PublishingQueue, entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    entry.scheduled_for = datetime.now(timezone.utc)
    if entry.status in ("FAILED", "UPLOADING"):
        entry.status = "QUEUED"
    db.commit()
    published = agent.publish_due_entries()
    db.expire_all()
    return _queue_dict(db, db.get(models.PublishingQueue, entry_id)) | {"cycle_published": published}


@app.delete("/api/queue/{entry_id}", status_code=204)
def delete_queue_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(models.PublishingQueue, entry_id)
    if not entry:
        raise HTTPException(404, "Queue entry not found")
    db.delete(entry)
    db.commit()


# ---------- logs & alerts feed ----------

@app.get("/api/logs")
def logs(db: Session = Depends(get_db)):
    """Recent activity feed built from queue logs + failures (PRD 5.1)."""
    feed = []
    entries = (
        db.query(models.PublishingQueue)
        .order_by(models.PublishingQueue.created_at.desc())
        .limit(60).all()
    )
    for e in entries:
        if e.status == "SUCCESS" and e.published_at:
            feed.append({
                "at": _iso(e.published_at), "level": "SUCCESS",
                "message": f"Published {e.post_type} for video #{e.video_id}"
                           + (f" part {e.clip.part_number}" if e.clip else "")
                           + f" (fb: {e.fb_post_id})",
            })
        elif e.logs:
            feed.append({
                "at": _iso(e.updated_at or e.created_at),
                "level": "WARN" if e.status == "QUEUED" else "ERROR",
                "message": f"Queue #{e.id} ({e.post_type}): {e.logs[-300:]}",
            })
    failed_videos = (
        db.query(models.Video).filter(models.Video.status == "FAILED")
        .order_by(models.Video.updated_at.desc()).limit(20).all()
    )
    for v in failed_videos:
        feed.append({
            "at": _iso(v.updated_at), "level": "ERROR",
            "message": f"Video '{v.title}' failed: {(v.error_message or '')[-300:]}",
        })
    feed.sort(key=lambda item: item["at"] or "", reverse=True)
    return feed[:80]


# ---------- settings ----------

@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    return [
        {"key": s.key, "value": _mask(s.key, s.value), "description": s.description,
         "updated_at": _iso(s.updated_at)}
        for s in db.query(models.SystemSetting).order_by(models.SystemSetting.key).all()
    ]


@app.patch("/api/settings/{key}")
def update_setting(key: str, payload: SettingsPatch, db: Session = Depends(get_db)):
    row = db.get(models.SystemSetting, key)
    if not row:
        raise HTTPException(404, "Setting not found")
    row.value = payload.value
    db.commit()
    return {"key": key, "updated": True}


# ---------- live pipeline progress ----------

@app.get("/api/progress")
def progress(limit: int = 80, db: Session = Depends(get_db)):
    """Recent pipeline events, newest first (download/process/upload/publish)."""
    events = (
        db.query(models.JobEvent)
        .order_by(models.JobEvent.id.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [
        {
            "id": e.id, "stage": e.stage, "video_ref": e.video_ref,
            "title": e.title, "percent": e.percent, "detail": e.detail,
            "created_at": _iso(e.created_at),
        }
        for e in events
    ]


# ---------- discover: keyword search -> pipeline ----------

@app.get("/api/keywords")
def keyword_templates():
    """Curated keyword template groups for the Discover panel."""
    return {"groups": keywords.KEYWORD_GROUPS, "default": keywords.DEFAULT_KEYWORD}


@app.post("/api/discover")
def discover(payload: DiscoverIn):
    """Search YouTube by keyword (dynamic input from the dashboard)."""
    err = keywords.validate(payload.keyword)
    if err:
        raise HTTPException(422, err)
    try:
        results = ingestion_mod.search_youtube(
            keywords.expand(payload.keyword, payload.limit), payload.limit
        )
    except Exception as exc:  # noqa: BLE001 - surface search failures to UI
        raise HTTPException(502, f"Search failed: {str(exc)[:300]}")
    return {"keyword": payload.keyword, "count": len(results), "results": results}


@app.post("/api/discover/add", status_code=201)
def discover_add(payload: DiscoverAddIn, db: Session = Depends(get_db)):
    """Send a discovered video into the pipeline (status PENDING)."""
    if db.query(models.Video).filter_by(source_video_id=payload.video_id).first():
        raise HTTPException(409, "Video already in pipeline")
    video = models.Video(
        source_video_id=payload.video_id,
        title=payload.title[:500],
        duration=payload.duration,
        original_url=payload.url,
    )
    db.add(video)
    db.commit()
    return {"id": video.id, "source_video_id": video.source_video_id, "status": video.status}


# ---------- manual triggers (PRD 5.1: Run Cron Now / Cleanup) ----------

@app.post("/api/run-cycle")
def run_cycle(background: BackgroundTasks):
    background.add_task(agent.run_all_once)
    return {"started": True}


@app.post("/api/cleanup")
def cleanup():
    removed = agent.run_garbage_collector()
    return {"files_removed": removed}


# ---------- helpers ----------

def _iso(dt):
    return dt.isoformat() if dt else None


def _mask(key: str, value: str) -> str:
    if any(secret in key for secret in ("token", "secret", "password")) and value:
        return value[:6] + "***" if len(value) > 6 else "***"
    return value


def _video_dict(v: models.Video) -> dict:
    return {
        "id": v.id, "source_video_id": v.source_video_id, "title": v.title,
        "duration": v.duration, "status": v.status,
        "error_message": v.error_message,
        "original_url": v.original_url,
        "created_at": _iso(v.created_at),
        "clips": [
            {"id": c.id, "part_number": c.part_number, "status": c.status,
             "duration": c.duration, "overlay_title": c.overlay_title}
            for c in v.clips
        ],
    }


def _queue_dict(db: Session, e: models.PublishingQueue) -> dict:
    video = db.get(models.Video, e.video_id)
    clip = db.get(models.Clip, e.clip_id) if e.clip_id else None
    return {
        "id": e.id, "video_id": e.video_id, "clip_id": e.clip_id,
        "post_type": e.post_type,
        "title": clip.overlay_title if clip else (video.title if video else None),
        "part_number": clip.part_number if clip else None,
        "scheduled_for": _iso(e.scheduled_for), "status": e.status,
        "fb_post_id": e.fb_post_id, "retry_count": e.retry_count,
        "logs": e.logs, "published_at": _iso(e.published_at),
    }
