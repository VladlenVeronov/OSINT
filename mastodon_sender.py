"""
OSINT Agent — публікація в Mastodon
Формат: тільки англійська мова, language="en" для автоперекладу.
"""

import requests
from config import MASTO_INSTANCE, MASTO_TOKEN, MASTO_ENABLED
from hashtags import build as build_tags

LEVEL_CONFIG = {
    "RED":    {"icon": "🔴"},
    "YELLOW": {"icon": "🟡"},
    "GREEN":  {"icon": "🟢"},
}


def _flag(code: str) -> str:
    code = code.upper().strip()
    if len(code) == 2 and code.isalpha():
        return chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)
    return ""


def _country_flags(countries: list) -> str:
    flags = [_flag(c) for c in (countries or [])[:3] if _flag(c)]
    return " ".join(flags)


def format_post(alert: dict) -> str:
    """Пост англійською, 5-6 хештегів."""
    cfg        = LEVEL_CONFIG.get(alert.get("level", "GREEN"), LEVEL_CONFIG["GREEN"])
    icon       = cfg["icon"]
    imp        = alert.get("importance", 1)
    alert_type = alert.get("type", "")
    countries  = _country_flags(alert.get("countries", []))
    note       = alert.get("note", "")

    title_en      = alert.get("title_en", "")
    body_en       = alert.get("body_en", "")
    conclusion_en = alert.get("conclusion_en", "")

    hashtags = build_tags("mastodon", alert.get("tags", []), alert.get("level", "GREEN"))

    header = f"{icon} {alert_type} | {imp}/10"
    if countries:
        header += f"\n{countries}"

    note_line = f"\n\n💬 {note}" if note else ""

    # RED: посилання на WP статтю
    level  = alert.get("level", "GREEN")
    wp_url = alert.get("wp_url", "")
    link_line = f"\n\n🔗 {wp_url}" if (level == "RED" and wp_url) else ""

    return (
        f"{header}\n\n"
        f"{title_en}\n"
        f"{body_en}"
        f"{note_line}"
        f"{link_line}\n\n"
        f"{hashtags}"
    )


def send(alert: dict) -> bool:
    """Публікує alert у Mastodon з language=en для автоперекладу."""
    if not MASTO_ENABLED or not MASTO_INSTANCE or not MASTO_TOKEN:
        return False

    text = format_post(alert)
    try:
        resp = requests.post(
            f"{MASTO_INSTANCE.rstrip('/')}/api/v1/statuses",
            headers={"Authorization": f"Bearer {MASTO_TOKEN}"},
            data={"status": text, "language": "en"},
            timeout=15,
        )
        return resp.status_code in (200, 201)
    except Exception:
        return False
