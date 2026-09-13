"""Central configuration for the Automated Video Syndication Agent.

Values resolve in order: environment variable -> .env file -> default.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# ===== Database =====
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///system.db")

# ===== Facebook Page =====
FB_PAGE_ID: str = os.getenv("FB_PAGE_ID", "")
FB_PAGE_ACCESS_TOKEN: str = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
FB_GRAPH_VERSION: str = os.getenv("FB_GRAPH_VERSION", "v19.0")

# ===== Telegram Alerts =====
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ===== Paths =====
DOWNLOADS_DIR: str = os.getenv("DOWNLOADS_DIR", "downloads")
PROCESSED_DIR: str = os.getenv("PROCESSED_DIR", "processed")

# ===== Automation params (PRD 6 - drip feeding) =====
DRIP_FEED_FULL_PER_DAY: int = int(os.getenv("DRIP_FEED_FULL_PER_DAY", "2"))
DRIP_FEED_REELS_PER_DAY: int = int(os.getenv("DRIP_FEED_REELS_PER_DAY", "4"))
SCAN_INTERVAL_MINUTES: int = int(os.getenv("SCAN_INTERVAL_MINUTES", "360"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))

# ===== Processing params (PRD 4.2) =====
WATERMARK_TEXT: str = os.getenv("WATERMARK_TEXT", "Drachin Indo")
CLIPS_MIN: int = int(os.getenv("CLIPS_MIN", "3"))
CLIPS_MAX: int = int(os.getenv("CLIPS_MAX", "5"))
CLIP_DURATION_MIN_SEC: int = int(os.getenv("CLIP_DURATION_MIN_SEC", "30"))
CLIP_DURATION_MAX_SEC: int = int(os.getenv("CLIP_DURATION_MAX_SEC", "60"))

# ===== Safety =====
# true = validate pipeline without calling Facebook (dry-run mode)
DRY_RUN: bool = os.getenv("DRY_RUN", "true").strip().lower() in ("1", "true", "yes")
