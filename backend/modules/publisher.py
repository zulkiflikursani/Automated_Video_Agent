"""Publishing module (PRD 4.3): Facebook Graph API uploader.

Dry-run mode (DRY_RUN=true, the default): validates payloads and file
integrity, returns a synthetic post id, and never touches Facebook. This lets
the whole pipeline run end-to-end safely until real Page credentials are set.
"""
import logging
import os
import uuid

import requests

from backend import config

logger = logging.getLogger(__name__)


class PublishingError(RuntimeError):
    pass


class MissingCredentials(PublishingError):
    pass


def _validate_media_file(path: str) -> int:
    """Ensure the media file exists and is non-trivial; returns its size."""
    if not path or not os.path.exists(path):
        raise PublishingError(f"Media file missing: {path}")
    size = os.path.getsize(path)
    if size < 1024:
        raise PublishingError(f"Media file suspiciously small ({size} bytes): {path}")
    return size


def upload_full_video(
    page_id: str,
    page_access_token: str,
    video_path: str,
    title: str,
    description: str,
) -> dict:
    """Upload a regular page video (non-resumable simple POST per PRD 4.3)."""
    size = _validate_media_file(video_path)
    if config.DRY_RUN:
        logger.info("[DRY-RUN] Full video upload validated: %s (%d bytes)", video_path, size)
        return {"post_id": f"dryrun_full_{uuid.uuid4().hex[:12]}", "dry_run": True}

    if not page_id or not page_access_token:
        raise MissingCredentials("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not configured")

    url = f"https://graph-video.facebook.com/{config.FB_GRAPH_VERSION}/{page_id}/videos"
    payload = {
        "title": title,
        "description": description,
        "access_token": page_access_token,
    }
    with open(video_path, "rb") as video_file:
        response = requests.post(url, data=payload, files={"source": video_file}, timeout=1800)
    result = response.json()
    if "error" in result:
        raise PublishingError(f"FB video API error: {result['error']}")
    return result


def upload_reels_video(
    page_id: str,
    page_access_token: str,
    video_path: str,
    caption: str,
) -> dict:
    """Upload a Reel via the 3-phase protocol: start -> binary PUT -> finish."""
    size = _validate_media_file(video_path)
    if config.DRY_RUN:
        logger.info("[DRY-RUN] Reels upload validated: %s (%d bytes)", video_path, size)
        return {"post_id": f"dryrun_reel_{uuid.uuid4().hex[:12]}", "dry_run": True}

    if not page_id or not page_access_token:
        raise MissingCredentials("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not configured")

    api_url = f"https://graph.facebook.com/{config.FB_GRAPH_VERSION}/{page_id}/video_reels"
    init_res = requests.post(
        api_url,
        data={"upload_phase": "start", "access_token": page_access_token},
        timeout=60,
    ).json()
    if "error" in init_res:
        raise PublishingError(f"FB reels start error: {init_res['error']}")
    video_id = init_res.get("video_id")
    upload_url = init_res.get("upload_url")
    if not video_id or not upload_url:
        raise PublishingError(f"FB reels start response incomplete: {init_res}")

    with open(video_path, "rb") as f:
        rupload = requests.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {page_access_token}",
                "offset": "0",
                "file_size": str(size),
            },
            data=f,
            timeout=1800,
        )
    if rupload.status_code >= 400:
        raise PublishingError(f"FB reels upload failed ({rupload.status_code}): {rupload.text[:500]}")

    finish_res = requests.post(
        api_url,
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": caption,
            "access_token": page_access_token,
        },
        timeout=60,
    ).json()
    if "error" in finish_res:
        raise PublishingError(f"FB reels finish error: {finish_res['error']}")
    return finish_res
