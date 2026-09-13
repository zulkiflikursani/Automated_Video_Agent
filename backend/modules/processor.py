"""Processing module (PRD 4.2): FFmpeg dual-format pipeline.

- Full video (16:9): brightness/contrast lift, watermark, pitch/tempo shift.
- Reels clip (9:16): blurred background + center foreground + title/PART overlays.

Text overlays are pre-rendered as transparent PNGs (Pillow/FreeType) and
composited with the `overlay` filter. This avoids a hard dependency on the
ffmpeg `drawtext` filter, which is absent in some distribution builds
(e.g. Homebrew ffmpeg 9.x without libfreetype) while producing identical
visuals to the PRD's drawtext spec.
"""
import logging
import os
import shlex
import subprocess
import tempfile
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from backend import config

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


class ProcessingError(RuntimeError):
    pass


def _run(cmd: list) -> subprocess.CompletedProcess:
    logger.info("FFmpeg: %s", shlex.join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "")[-1500:]
        raise ProcessingError(f"ffmpeg failed (exit {result.returncode}):\n{tail}")
    return result


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def render_text_png(
    text: str,
    out_path: str,
    fontsize: int = 48,
    fg: Tuple[int, int, int, int] = (255, 255, 255, 255),
    bg: Optional[Tuple[int, int, int, int]] = (0, 0, 0, 153),
    pad: int = 14,
) -> str:
    """Render text (+ optional box) to a transparent PNG; returns the path."""
    font = _load_font(fontsize)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
    width = (right - left) + 2 * pad
    height = (bottom - top) + 2 * pad

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if bg is not None:
        draw.rectangle([0, 0, width - 1, height - 1], fill=bg)
    draw.text((pad - left, pad - top), text, font=font, fill=fg)
    img.save(out_path)
    return out_path


def process_full_video(input_path: str, output_path: str, watermark_text: Optional[str] = None) -> str:
    """Apply PRD 4.2 full-video transform; returns output path."""
    wm = watermark_text if watermark_text is not None else config.WATERMARK_TEXT
    tmp_png = os.path.join(tempfile.gettempdir(), f"ava_wm_{os.getpid()}.png")
    try:
        render_text_png(
            wm, tmp_png,
            fontsize=24,
            fg=(255, 255, 255, 204),  # white@0.8
            bg=None,
        )
        filter_complex = (
            "[0:v]eq=brightness=0.03:contrast=1.03[base];"
            "[base][1:v]overlay=x=W-w-20:y=20[v];"
            "[0:a]atempo=1.02,asetrate=44100*1.01[a]"
        )
        cmd = [
            "ffmpeg", "-y", "-i", input_path, "-i", tmp_png,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            output_path,
        ]
        _run(cmd)
    finally:
        if os.path.exists(tmp_png):
            os.remove(tmp_png)

    if not os.path.exists(output_path):
        raise ProcessingError(f"Expected output missing: {output_path}")
    return output_path


def generate_reels_clip(
    input_path: str,
    output_path: str,
    start_sec: int,
    duration_sec: int,
    part_num: int,
    title_text: str,
) -> str:
    """Cut a 9:16 Reels clip with blurred background and overlays; returns output path."""
    tmp_title = os.path.join(tempfile.gettempdir(), f"ava_title_{os.getpid()}.png")
    tmp_part = os.path.join(tempfile.gettempdir(), f"ava_part_{os.getpid()}.png")
    try:
        render_text_png(
            title_text, tmp_title,
            fontsize=38,
            fg=(255, 255, 0, 255),      # yellow
            bg=(0, 0, 0, 153),          # black@0.6
        )
        render_text_png(
            f"PART {part_num}", tmp_part,
            fontsize=48,
            fg=(255, 255, 255, 255),    # white
            bg=(204, 0, 0, 204),        # red@0.8
        )
        filter_complex = (
            f"[0:v]trim=start={start_sec}:duration={duration_sec},setpts=PTS-STARTPTS,split[v1][v2];"
            f"[v1]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg];"
            f"[v2]scale=1080:-1,crop=1080:min(ih\\,1080)[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
            f"[base][1:v]overlay=(W-w)/2:180[t];"
            f"[t][2:v]overlay=(W-w)/2:H-h-220[v];"
            f"[v]format=yuv420p[outv];"
            f"[0:a]atrim=start={start_sec}:duration={duration_sec},asetpts=PTS-STARTPTS[outa]"
        )
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-i", tmp_title, "-i", tmp_part,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            output_path,
        ]
        _run(cmd)
    finally:
        for path in (tmp_title, tmp_part):
            if os.path.exists(path):
                os.remove(path)

    if not os.path.exists(output_path):
        raise ProcessingError(f"Expected output missing: {output_path}")
    return output_path
