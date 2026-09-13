"""Default rows seeded into system_settings on first init."""
from backend import config

DEFAULT_SETTINGS = {
    "fb_page_id": (config.FB_PAGE_ID, "Facebook Page ID used for publishing"),
    "fb_page_access_token": (config.FB_PAGE_ACCESS_TOKEN, "Facebook Page long-lived access token"),
    "fb_graph_version": (config.FB_GRAPH_VERSION, "Facebook Graph API version"),
    "telegram_bot_token": (config.TELEGRAM_BOT_TOKEN, "Telegram bot token for alerts"),
    "telegram_chat_id": (config.TELEGRAM_CHAT_ID, "Telegram chat ID for alerts"),
    "drip_feed_full_per_day": (str(config.DRIP_FEED_FULL_PER_DAY), "Max full videos published per 24h"),
    "drip_feed_reels_per_day": (str(config.DRIP_FEED_REELS_PER_DAY), "Max Reels published per 24h"),
    "watermark_text": (config.WATERMARK_TEXT, "Watermark drawn on full videos"),
    "dry_run": (str(config.DRY_RUN).lower(), "If true, publishing is validated but not sent to Facebook"),
}
