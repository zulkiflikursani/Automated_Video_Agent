"""Phase 3 verification: clip planner + real FFmpeg dual-format processing."""
import json
import subprocess

import pytest

from backend.modules import clip_planner, processor


# ---------- clip planner (pure logic) ----------

def test_plan_clips_long_video_yields_3_to_5_valid_parts():
    clips = clip_planner.plan_clips(2400)  # 40 minutes
    assert clip_planner.config.CLIPS_MIN <= len(clips) <= clip_planner.config.CLIPS_MAX
    for i, clip in enumerate(clips, start=1):
        assert clip["part_number"] == i
        assert clip_planner.config.CLIP_DURATION_MIN_SEC <= clip["duration"] <= clip_planner.config.CLIP_DURATION_MAX_SEC
        assert clip["end_time_sec"] > clip["start_time_sec"]
    starts = [c["start_time_sec"] for c in clips]
    assert starts == sorted(starts)


def test_plan_clips_short_video_single_window():
    clips = clip_planner.plan_clips(45)
    assert len(clips) == 1
    assert clips[0]["duration"] == 45


def test_plan_clips_invalid_duration():
    assert clip_planner.plan_clips(None) == []
    assert clip_planner.plan_clips(0) == []


# ---------- FFmpeg (real binary) ----------

@pytest.fixture(scope="module")
def synthetic_video(tmp_path_factory):
    """Build a 120s synthetic 16:9 video with a 440Hz tone."""
    out = tmp_path_factory.mktemp("media") / "raw.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=120:size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=120",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-shortest",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out)


def probe(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def test_process_full_video_produces_transformed_output(synthetic_video, tmp_path):
    out = str(tmp_path / "full.mp4")
    processor.process_full_video(synthetic_video, out, watermark_text="Drachin Indo")

    info = probe(out)
    video_streams = [s for s in info["streams"] if s["codec_type"] == "video"]
    audio_streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert video_streams and audio_streams
    assert video_streams[0]["width"] == 640
    assert float(info["format"]["duration"]) == pytest.approx(120, abs=5)


def test_generate_reels_clip_produces_vertical_1080x1920(synthetic_video, tmp_path):
    out = str(tmp_path / "reel.mp4")
    processor.generate_reels_clip(
        synthetic_video, out, start_sec=30, duration_sec=30, part_num=1, title_text="Uji Klip"
    )

    info = probe(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert float(info["format"]["duration"]) == pytest.approx(30, abs=3)


def test_processing_error_on_bad_input(tmp_path):
    with pytest.raises(processor.ProcessingError):
        processor.process_full_video(str(tmp_path / "nope.mp4"), str(tmp_path / "out.mp4"))
