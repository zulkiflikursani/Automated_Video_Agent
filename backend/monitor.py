"""Progress monitor: writes JobEvent rows so the dashboard can show live pipeline
progress (download %, encode %, upload %, publish results) across processes.

Kept intentionally lightweight: fire-and-forget writes, never breaks the
pipeline on failure.
"""
import logging

from backend import models
from backend.db import session_scope

logger = logging.getLogger(__name__)


def event(stage: str, video_ref: str = "", title: str = "", percent=None, detail: str = "") -> None:
    """Record a pipeline progress event. Failures are logged, never raised."""
    try:
        with session_scope() as db:
            db.add(
                models.JobEvent(
                    stage=stage,
                    video_ref=(video_ref or "")[:255],
                    title=(title or "")[:500],
                    percent=percent,
                    detail=(detail or "")[:2000],
                )
            )
    except Exception:  # noqa: BLE001 - monitoring must never break the pipeline
        logger.warning("monitor.event failed", exc_info=True)
