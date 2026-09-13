"""SQLAlchemy models mirroring PRD section 3 (v1.1) schemas."""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from backend.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    url = Column(Text, nullable=False, unique=True)
    platform = Column(String(50), default="youtube")
    is_active = Column(Boolean, default=True)
    check_interval_hours = Column(Integer, default=6)
    last_checked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    videos = relationship(
        "Video", back_populates="source", passive_deletes=True
    )


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="SET NULL"))
    source_video_id = Column(String(255), unique=True, nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    duration = Column(Integer)  # seconds
    original_url = Column(Text, nullable=False)
    local_raw_path = Column(Text)
    # PENDING, DOWNLOADING, PROCESSING, READY, PUBLISHED, FAILED
    status = Column(String(50), default="PENDING")
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    source = relationship("Source", back_populates="videos")
    clips = relationship(
        "Clip", back_populates="video", cascade="all, delete-orphan", passive_deletes=True
    )
    queue_entries = relationship(
        "PublishingQueue",
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Clip(Base):
    __tablename__ = "clips"

    id = Column(Integer, primary_key=True)
    video_id = Column(
        Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    part_number = Column(Integer, nullable=False)
    start_time_sec = Column(Integer, nullable=False)
    end_time_sec = Column(Integer, nullable=False)
    duration = Column(Integer, nullable=False)
    local_clip_path = Column(Text)
    overlay_title = Column(String(255))
    # PENDING, PROCESSING, READY, PUBLISHED, FAILED
    status = Column(String(50), default="PENDING")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    video = relationship("Video", back_populates="clips")
    queue_entries = relationship(
        "PublishingQueue",
        back_populates="clip",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PublishingQueue(Base):
    __tablename__ = "publishing_queue"

    id = Column(Integer, primary_key=True)
    video_id = Column(
        Integer, ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    clip_id = Column(Integer, ForeignKey("clips.id", ondelete="CASCADE"))
    post_type = Column(String(20), nullable=False)  # REGULAR_VIDEO | REELS
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    fb_post_id = Column(String(255))
    # QUEUED, UPLOADING, SUCCESS, FAILED
    status = Column(String(50), default="QUEUED")
    retry_count = Column(Integer, default=0)
    logs = Column(Text)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    video = relationship("Video", back_populates="queue_entries")
    clip = relationship("Clip", back_populates="queue_entries")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    description = Column(Text)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
