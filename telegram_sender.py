"""
OSINT Agent — відправка в Telegram
Формат: тільки українська мова.
"""

import requests
from config import TG_BOT_TOKEN, TG_CHAT_ID, TG_THREAD_ID
from hashtags import build as build_tags

BASE = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"

LEVEL_CONFIG = {
    "RED":    {"icon": "🔴", "disable_notification": False},
    "YELLOW": {"icon": "🟡", "disable_notification": False},
    "GREEN":  {"icon": "🟢", "disable_notification": True},
}


def _flag(code: str) -> str:
    code = code.upper().strip()
    if len(code) == 2 and code.isalpha():
        return chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)
    return ""


def _country_flags(countries: list) -> str:
    flags = [_flag(c) for c in (countries or [])[:3] if _flag(c)]
    return " ".join(flags)


def format_message(alert: dict) -> str:
    cfg        = LEVEL_CONFIG.get(alert["level"], LEVEL_CONFIG["GREEN"])
    icon       = cfg["icon"]
    imp        = alert.get("importance", 1)
    alert_type = alert.get("type", "")
    countries  = _country_flags(alert.get("countries", []))
    tags       = build_tags("telegram", alert.get("tags", []), alert.get("level", "GREEN"))
    note       = alert.get("note", "")

    title_ua      = alert.get("title_ua", "")
    body_ua       = alert.get("body_ua", "")
    conclusion_ua = alert.get("conclusion_ua", "")

    header = f"{icon} {alert_type} | {imp}/10"
    if countries:
        header += f"\n{countries}"

    note_line = f"\n💬 <i>{note}</i>" if note else ""
    conclusion_line = f"\n\n<i>Висновок: {conclusion_ua}</i>" if conclusion_ua else ""

    # RED: додаємо посилання на WP статтю; YELLOW/GREEN: тільки текст без джерел
    level = alert.get("level", "GREEN")
    wp_url = alert.get("wp_url", "")
    link_line = f'\n\n🔗 <a href="{wp_url}">Читати на сайті</a>' if (level == "RED" and wp_url) else ""

    msg = (
        f"{header}\n\n"
        f"<b>{title_ua}</b>\n"
        f"{body_ua}"
        f"{conclusion_line}"
        f"{note_line}"
        f"{link_line}\n\n"
        f"{tags}"
    )
    return msg


def send_alert(alert: dict) -> bool:
    cfg   = LEVEL_CONFIG.get(alert["level"], LEVEL_CONFIG["GREEN"])
    text  = format_message(alert)
    silent = cfg["disable_notification"]

    payload = {
        "chat_id":                  TG_CHAT_ID,
        "message_thread_id":        TG_THREAD_ID,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_notification":     silent,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(f"{BASE}/sendMessage", json=payload, timeout=15)
        return resp.status_code == 200 and resp.json().get("ok", False)
    except Exception:
        return False


def send_error_log(msg: str):
    """Помилки агента — тільки в адмін чат."""
    from config import ADMIN_CHAT_ID, ADMIN_THREAD_ID
    if not ADMIN_CHAT_ID:
        return
    payload = {
        "chat_id":              ADMIN_CHAT_ID,
        "text":                 f"⚠️ <b>OSINT Agent:</b> {msg}",
        "parse_mode":           "HTML",
        "disable_notification": True,
    }
    if ADMIN_THREAD_ID:
        payload["message_thread_id"] = ADMIN_THREAD_ID
    try:
        requests.post(f"{BASE}/sendMessage", json=payload, timeout=10)
    except Exception:
        pass
