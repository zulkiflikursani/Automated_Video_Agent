"""Clip planning: split a long video into 3-5 Reels parts of 30-60 seconds.

Strategy: distribute clips evenly across the source timeline, skipping the
first `lead_in` seconds (intros are usually logos) and the last `tail_out`
seconds (end cards), so each part lands mid-story.
"""
from backend import config

LEAD_IN_SEC = 60
TAIL_OUT_SEC = 60


def plan_clips(duration_sec: int) -> list:
    """Return [{part_number, start_time_sec, end_time_sec, duration}] for a video.

    Falls back to a single full-length clip window when the source is too
    short for the lead-in/tail-out margins.
    """
    if duration_sec is None or duration_sec <= 0:
        return []

    usable_start = LEAD_IN_SEC if duration_sec > LEAD_IN_SEC + TAIL_OUT_SEC else 0
    usable_end = duration_sec - TAIL_OUT_SEC if duration_sec > LEAD_IN_SEC + TAIL_OUT_SEC else duration_sec
    usable = usable_end - usable_start

    if usable < config.CLIP_DURATION_MIN_SEC:
        # Too short to cut: one clip covering what exists.
        window = min(duration_sec, config.CLIP_DURATION_MAX_SEC)
        return [
            {
                "part_number": 1,
                "start_time_sec": 0,
                "end_time_sec": window,
                "duration": window,
            }
        ]

    # Pick clip count so each part fits within [min, max] duration.
    target = usable / max(1, config.CLIPS_MAX)
    if target >= config.CLIP_DURATION_MIN_SEC:
        count = config.CLIPS_MAX
    else:
        count = max(1, usable // config.CLIP_DURATION_MIN_SEC)
    count = max(config.CLIPS_MIN if usable >= config.CLIPS_MIN * config.CLIP_DURATION_MIN_SEC else 1,
                min(count, config.CLIPS_MAX))

    each = usable // count
    each = min(max(each, config.CLIP_DURATION_MIN_SEC), config.CLIP_DURATION_MAX_SEC)

    clips = []
    start = usable_start + max(0, (usable - each * count) // 2)  # center the strip
    for part in range(1, count + 1):
        end = min(start + each, usable_end)
        clips.append(
            {
                "part_number": part,
                "start_time_sec": int(start),
                "end_time_sec": int(end),
                "duration": int(end - start),
            }
        )
        start += each
        if start >= usable_end:
            break
    return clips
