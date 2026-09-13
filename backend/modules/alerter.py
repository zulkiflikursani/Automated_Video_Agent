"""Telegram alerting (PRD 6): incident notifications + token expiry watch."""
import logging
from datetime import datetime, timedelta, timezone

import requests

from backend import config
from backend.db import session_scope
from backend.models import SystemSetting

logger = logging.getLogger(__name__)


def _telegram_credentials():
    with session_scope() as db:
        rows = {s.key: s.value for s in db.query(SystemSetting).all()}
    token = rows.get("telegram_bot_token") or config.TELEGRAM_BOT_TOKEN
    chat_id = rows.get("telegram_chat_id") or config.TELEGRAM_CHAT_ID
    return token, chat_id


def send_alert(message: str) -> bool:
    """Send a Telegram message; returns True when delivered (or dry-noted)."""
    token, chat_id = _telegram_credentials()
    if not token or not chat_id:
        logger.warning("[ALERT not sent, no Telegram creds] %s", message)
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": f"[VideoAgent] {message}"},
            timeout=30,
        )
        ok = resp.status_code == 200
        if not ok:
            logger.error("Telegram alert failed (%s): %s", resp.status_code, resp.text[:200])
        return ok
    except requests.RequestException as exc:
        logger.error("Telegram alert error: %s", exc)
        return False


def check_token_expiry() -> bool:
    """Alert when the FB token expires within 5 days (PRD risk table).

    Reads optional system_setting `fb_token_expires_at` (ISO-8601).
    """
    with session_scope() as db:
        raw = db.get(SystemSetting, "fb_token_expires_at")
        value = raw.value if raw else None
    if not value:
        return False
    try:
        expires_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("fb_token_expires_at is not ISO-8601: %r", value)
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    remaining = expires_at - datetime.now(timezone.utc)
    if remaining <= timedelta(days=5):
        send_alert(
            f"WARNING: Facebook access token expires in "
            f"{max(0, remaining.days)} day(s) ({expires_at.isoformat()}). "
            "Please renew FB_PAGE_ACCESS_TOKEN."
        )
        return True
    return False
