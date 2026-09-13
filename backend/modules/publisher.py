"""Publishing module (PRD 4.3): Facebook Graph API uploader.

Dry-run mode (DRY_RUN=true, the default): validates payloads and file
integrity, returns a synthetic post id, and never touches Facebook. This lets
the whole pipeline run end-to-end safely until real Page credentials are set.
"""
import logging
import os
import time
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
    """Upload a regular page video. Uses the resumable/chunked protocol for
    large files (>20MB) and the simple multipart POST for small ones."""
    size = _validate_media_file(video_path)
    if config.DRY_RUN:
        logger.info("[DRY-RUN] Full video upload validated: %s (%d bytes)", video_path, size)
        return {"post_id": f"dryrun_full_{uuid.uuid4().hex[:12]}", "dry_run": True}

    if not page_id or not page_access_token:
        raise MissingCredentials("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not configured")

    if size > 20 * 1024 * 1024:
        return upload_full_video_resumable(
            page_id, page_access_token, video_path, title, description
        )

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


def upload_full_video_resumable(
    page_id: str,
    page_access_token: str,
    video_path: str,
    title: str,
    description: str,
    chunk_size: int = 8 * 1024 * 1024,
    on_progress=None,
) -> dict:
    """Resumable/chunked upload (start -> transfer per chunk -> finish).

    Required for large files; FB returns empty/garbled responses for single
    huge multipart POSTs. Docs: graph-video /videos resumable protocol.
    """
    size = _validate_media_file(video_path)
    if config.DRY_RUN:
        logger.info("[DRY-RUN] Resumable upload validated: %s (%d bytes)", video_path, size)
        return {"post_id": f"dryrun_full_{uuid.uuid4().hex[:12]}", "dry_run": True}

    if not page_id or not page_access_token:
        raise MissingCredentials("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not configured")

    url = f"https://graph-video.facebook.com/{config.FB_GRAPH_VERSION}/{page_id}/videos"

    # --- start phase ---
    start_res = requests.post(
        url,
        data={
            "upload_phase": "start",
            "file_size": str(size),
            "access_token": page_access_token,
        },
        timeout=60,
    ).json()
    if "error" in start_res:
        raise PublishingError(f"FB resumable start error: {start_res['error']}")
    upload_full_video_resumable._last_pct = -10
    video_id = start_res.get("video_id")
    session_id = start_res.get("upload_session_id")
    start_offset = int(start_res.get("start_offset", 0))
    end_offset = int(start_res.get("end_offset", chunk_size))
    if not video_id or not session_id:
        raise PublishingError(f"FB resumable start incomplete: {start_res}")
    logger.info("Resumable start: video_id=%s, first window=%d-%d", video_id, start_offset, end_offset)

    # --- transfer phase ---
    # NOTE: FB's transfer response for graph-video /videos often returns just
    # {"id": ...} WITHOUT the next start/end offsets. When that happens we
    # must ask the session where to continue (upload_phase=query) and send a
    # regular-size chunk; defaulting the window to the stale value produced
    # zero-length chunks and error 381.
    DEFAULT_WINDOW = chunk_size
    with open(video_path, "rb") as f:
        while start_offset < size:
            chunk_len = max(1, end_offset - start_offset)
            f.seek(start_offset)
            chunk = f.read(chunk_len)
            result = None
            last_err = ""
            for attempt in range(1, 9):  # FB 381s/connection drops are often transient
                try:
                    transfer_res = requests.post(
                        url,
                        headers={
                            "Authorization": f"OAuth {page_access_token}",
                            "file_size": str(size),
                            "offset": str(start_offset),
                        },
                        files={
                            "file_chunk": (
                                os.path.basename(video_path), chunk, "video/mp4"
                            )
                        },
                        timeout=1800,
                    )
                    result = transfer_res.json()
                except (ValueError, requests.RequestException) as exc:
                    last_err = f"attempt {attempt}: {str(exc)[:120]}"
                    logger.warning("Chunk @%d %s", start_offset, last_err)
                    result = None
                    time.sleep(min(2 ** attempt, 30))  # backoff 2,4,8,16,30,30,30
                    continue
                if "error" in result:
                    last_err = str(result["error"])[:150]
                    logger.warning("Chunk @%d attempt %d failed: %s", start_offset, attempt, last_err)
                    result = None
                    time.sleep(min(2 ** attempt, 30))
                    continue
                break
            if result is None:
                raise PublishingError(
                    f"FB transfer failed after retries at offset {start_offset}: {last_err}"
                )

            if "start_offset" in result:
                # FB told us the next window explicitly.
                start_offset = int(result["start_offset"])
                end_offset = int(result.get("end_offset", start_offset + DEFAULT_WINDOW))
            else:
                # Response lacks offsets: query the session for authoritative state.
                query = requests.post(
                    url,
                    data={
                        "upload_phase": "query",
                        "video_id": video_id,
                        "upload_session_id": session_id,
                        "access_token": page_access_token,
                    },
                    timeout=60,
                ).json()
                q_start = int(query.get("start_offset", start_offset + chunk_len))
                q_end = int(query.get("end_offset", q_start + DEFAULT_WINDOW))
                if q_start <= start_offset and q_end <= start_offset:
                    # Query unhelpful; advance by what we just sent.
                    start_offset = start_offset + chunk_len
                    end_offset = start_offset + DEFAULT_WINDOW
                else:
                    start_offset, end_offset = q_start, max(q_end, q_start + 1)
            end_offset = min(max(end_offset, start_offset + 1), size)
            pct = int(100 * start_offset / size)
            logger.info("Resumable progress: %d/%d bytes (%.0f%%), next window=%d-%d",
                        start_offset, size, pct, start_offset, end_offset)
            if on_progress and pct >= getattr(upload_full_video_resumable, "_last_pct", -1) + 10:
                upload_full_video_resumable._last_pct = pct
                on_progress(min(pct, 99))

    # --- finish phase ---
    finish_res = requests.post(
        url,
        data={
            "upload_phase": "finish",
            "access_token": page_access_token,
            "video_id": video_id,
            "upload_session_id": session_id,
            "title": title,
            "description": description,
        },
        timeout=60,
    ).json()
    if "error" in finish_res:
        raise PublishingError(f"FB resumable finish error: {finish_res['error']}")
    logger.info("Resumable finish: %s", finish_res)
    # finish only returns {"success": true}; surface the real video id
    return {**finish_res, "id": video_id}


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
