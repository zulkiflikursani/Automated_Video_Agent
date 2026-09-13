"""Phase 4 verification: publisher dry-run + mocked Facebook API flows."""
from unittest import mock

import pytest

from backend.modules import publisher


@pytest.fixture()
def media_file(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x" * 2048)  # above the 1KB sanity threshold
    return str(path)


@pytest.fixture()
def live_mode():
    """Temporarily flip DRY_RUN off to exercise real API code paths."""
    with mock.patch.object(publisher.config, "DRY_RUN", False):
        yield


# ---------- dry-run (default mode) ----------

def test_dry_run_full_video(media_file):
    result = publisher.upload_full_video("PAGE", "TOKEN", media_file, "T", "D")
    assert result["dry_run"] is True
    assert result["post_id"].startswith("dryrun_full_")


def test_dry_run_reels(media_file):
    result = publisher.upload_reels_video("PAGE", "TOKEN", media_file, "caption")
    assert result["dry_run"] is True
    assert result["post_id"].startswith("dryrun_reel_")


def test_missing_media_file_rejected():
    with pytest.raises(publisher.PublishingError):
        publisher.upload_full_video("PAGE", "TOKEN", "/nonexistent.mp4", "T", "D")


def test_tiny_media_file_rejected(tmp_path):
    tiny = tmp_path / "tiny.mp4"
    tiny.write_bytes(b"x" * 10)
    with pytest.raises(publisher.PublishingError):
        publisher.upload_reels_video("PAGE", "TOKEN", str(tiny), "c")


def test_live_mode_without_credentials_raises(media_file, live_mode):
    with pytest.raises(publisher.MissingCredentials):
        publisher.upload_full_video("", "", media_file, "T", "D")
    with pytest.raises(publisher.MissingCredentials):
        publisher.upload_reels_video("", "", media_file, "c")


# ---------- live paths with mocked requests ----------

def test_live_full_video_success(media_file, live_mode):
    fake = mock.Mock()
    fake.json.return_value = {"post_id": "12345_67890"}
    with mock.patch.object(publisher.requests, "post", return_value=fake) as post:
        result = publisher.upload_full_video("PAGE", "TOKEN", media_file, "T", "D")

    assert result["post_id"] == "12345_67890"
    posted_url = post.call_args.args[0]
    assert "graph-video.facebook.com" in posted_url and "/PAGE/videos" in posted_url


def test_live_full_video_api_error(media_file, live_mode):
    fake = mock.Mock()
    fake.json.return_value = {"error": {"message": "boom", "code": 190}}
    with mock.patch.object(publisher.requests, "post", return_value=fake):
        with pytest.raises(publisher.PublishingError, match="boom"):
            publisher.upload_full_video("PAGE", "TOKEN", media_file, "T", "D")


def test_live_reels_three_phase_flow(media_file, live_mode):
    init_fake = mock.Mock()
    init_fake.json.return_value = {"video_id": "VID", "upload_url": "https://rupload.fb/x"}

    binary_fake = mock.Mock(status_code=200, text="{}")

    finish_fake = mock.Mock()
    finish_fake.json.return_value = {"success": True}

    with mock.patch.object(publisher.requests, "post", side_effect=[init_fake, binary_fake, finish_fake]) as post:
        result = publisher.upload_reels_video("PAGE", "TOKEN", media_file, "caption")

    assert result == {"success": True}
    assert post.call_count == 3
    # Phase 2 binary upload must carry offset/file_size headers
    headers = post.call_args_list[1].kwargs["headers"]
    assert headers["offset"] == "0"
    assert headers["file_size"] == "2048"


def test_live_reels_binary_failure(media_file, live_mode):
    init_fake = mock.Mock()
    init_fake.json.return_value = {"video_id": "VID", "upload_url": "https://rupload.fb/x"}
    binary_fake = mock.Mock(status_code=500, text="server error")

    with mock.patch.object(publisher.requests, "post", side_effect=[init_fake, binary_fake]):
        with pytest.raises(publisher.PublishingError, match="500"):
            publisher.upload_reels_video("PAGE", "TOKEN", media_file, "caption")
