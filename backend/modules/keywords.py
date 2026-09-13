"""Curated keyword templates for the Discover panel.

Structure: groups of templates tuned for finding trending Chinese mini-drama
content that fits the Page (dubbed/subbed Indonesian, vertical-friendly,
episodic). Each template may repeat {n} for platform-specific result counts.
"""
from typing import Optional

KEYWORD_GROUPS = {
    "Trending Harian (ID)": [
        "drama cina sub indo {n}",
        "dracin terbaru 2026 full episode",
        "drama china viral hari ini sub indo",
        "drama cina terbaru 2026 full movie sub indo",
    ],
    "Mini Drama Viral": [
        "mini drama cina viral sub indo",
        "short drama china sub indo full",
        "drama cina pendek viral tiktok sub indo",
        "cerita cinta CEO sub indo mini drama",
    ],
    "Tropes Populer (CEO/Balas Dendam/Reinkarnasi)": [
        "drama cina CEO kontrak pernikahan sub indo",
        "drama cina balas dendam miliarder sub indo",
        "drama cina reinkarnasi keberuntungan sub indo",
        "drama cina penghinaan keluarga balas dendam sub indo",
    ],
    "Romansa & Fantasi": [
        "drama cina romantis komedi sub indo full",
        "drama cina fantasi sejarah sub indo",
        "drama cina pasangan mendadak sub indo",
        "drama cina batin duda janda miliarder sub indo",
    ],
    "Pencarian Berdasar Channel Populer": [
        "IANAI PRODUCTION drama full",
        "Semesta Dracin full episode",
        "KANDANG MADARA drama sub indo",
        "Raja Film drama cina full",
    ],
}

DEFAULT_KEYWORD = "drama cina sub indo {n}"
MAX_KEYWORD_LEN = 120


def expand(keyword: str, n: int = 10) -> str:
    """Fill {n} placeholders and trim to a sane length."""
    filled = (keyword or "").replace("{n}", str(n))
    return filled.strip()[:MAX_KEYWORD_LEN]


def validate(keyword: str) -> Optional[str]:
    """Return an error message when the keyword is unusable, else None."""
    if not keyword or not keyword.strip():
        return "Keyword is required"
    if len(keyword.strip()) > MAX_KEYWORD_LEN:
        return f"Keyword too long (max {MAX_KEYWORD_LEN} chars)"
    return None
