"""Ingestion module (PRD 4.1): yt-dlp based video discovery and download."""
import logging
import os

import yt_dlp

from backend import config

logger = logging.getLogger(__name__)


def _yt_base_opts() -> dict:
    """Common yt-dlp options (player clients beat YouTube's SABR web lock)."""
    clients = [c.strip() for c in config.YT_PLAYER_CLIENTS.split(",") if c.strip()]
    return {"quiet": True, "no_warnings": True, "extractor_args": {"youtube": {"player_client": clients}}} if clients else {"quiet": True, "no_warnings": True}


def list_source_videos(source_url: str) -> list:
    """Return flat entries [{id, title, url, duration}] for a channel/playlist URL."""
    opts = {
        **_yt_base_opts(),
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source_url, download=False)

    entries = info.get("entries") or []
    results = []
    for entry in entries:
        if not entry:
            continue
        results.append(
            {
                "id": entry.get("id"),
                "title": entry.get("title") or "Untitled",
                "url": entry.get("url") or entry.get("webpage_url") or source_url,
                "duration": entry.get("duration"),
            }
        )
    return results


def search_youtube(keyword: str, limit: int = 10) -> list:
    """Search YouTube for videos; returns [{id, title, channel, duration, views, url}]."""
    opts = {
        **_yt_base_opts(),
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max(1, min(limit, 30))}:{keyword}", download=False)
    results = []
    for entry in info.get("entries") or []:
        if not entry:
            continue
        results.append(
            {
                "id": entry.get("id"),
                "title": (entry.get("title") or "Untitled")[:500],
                "channel": entry.get("channel") or entry.get("uploader") or "",
                "duration": entry.get("duration"),
                "views": entry.get("view_count") or 0,
                "url": entry.get("url") or entry.get("webpage_url")
                or f"https://www.youtube.com/watch?v={entry.get('id')}",
            }
        )
    return results


def download_video(url: str, video_id: str, on_progress=None) -> str:
    """Download a single video into DOWNLOADS_DIR; return the local file path.

    `on_progress(percent)` is invoked on coarse steps for the dashboard.
    """
    os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)
    outtmpl = os.path.join(config.DOWNLOADS_DIR, f"{video_id}.%(ext)s")

    last_pct = {"value": -10}

    def _hook(d):
        if on_progress is None or d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if not total:
            return
        pct = int(d.get("downloaded_bytes", 0) * 100 / total)
        if pct - last_pct["value"] >= 10:  # coarse steps only
            last_pct["value"] = pct
            on_progress(min(pct, 99))

    opts = {
        **_yt_base_opts(),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "overwrites": True,
        "progress_hooks": [_hook],
    }
    logger.info("Downloading %s -> %s", url, outtmpl)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)

    if not os.path.exists(path):
        raise FileNotFoundError(f"yt-dlp reported success but file missing: {path}")
    return path
