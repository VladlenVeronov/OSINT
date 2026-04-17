"""
OSINT Agent — публікація в Bluesky
Формат: тільки англійська мова, ~300 символів, 3 хештеги.
"""

import requests
from config import BS_HANDLE, BS_APP_PASSWORD, BS_ENABLED
from hashtags import build as build_tags

BSKY_PDS      = "https://bsky.social"
BSKY_MAX_CHARS = 300

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


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def format_post(alert: dict) -> str:
    """Короткий пост англійською, ~300 символів, 3 хештеги."""
    cfg        = LEVEL_CONFIG.get(alert.get("level", "GREEN"), LEVEL_CONFIG["GREEN"])
    icon       = cfg["icon"]
    imp        = alert.get("importance", 1)
    alert_type = alert.get("type", "")
    countries  = _country_flags(alert.get("countries", []))

    title_en = alert.get("title_en", "")
    body_en  = alert.get("body_en", "")

    hashtags = build_tags("bluesky", alert.get("tags", []), alert.get("level", "GREEN"))

    header = f"{icon} {alert_type} | {imp}/10"
    if countries:
        header += f" {countries}"

    # RED: додаємо посилання на WP статтю
    level  = alert.get("level", "GREEN")
    wp_url = alert.get("wp_url", "")

    # Перше речення тіла
    body = body_en.split(". ")[0].rstrip(".")

    link_suffix = f"\n{wp_url}" if (level == "RED" and wp_url) else ""
    reserved  = len(header) + len(title_en) + len(hashtags) + len(link_suffix) + 5
    max_body  = BSKY_MAX_CHARS - reserved
    body      = _truncate(body, max(max_body, 40))

    return f"{header}\n\n{title_en}\n{body}{link_suffix}\n\n{hashtags}"


def _get_session() -> dict | None:
    try:
        resp = requests.post(
            f"{BSKY_PDS}/xrpc/com.atproto.server.createSession",
            json={"identifier": BS_HANDLE, "password": BS_APP_PASSWORD},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def send(alert: dict) -> bool:
    """Публікує alert у Bluesky. Повертає True якщо успішно."""
    if not BS_ENABLED or not BS_HANDLE or not BS_APP_PASSWORD:
        return False

    session = _get_session()
    if not session:
        return False

    text = format_post(alert)
    did  = session.get("did", "")
    jwt  = session.get("accessJwt", "")

    record = {
        "$type":     "app.bsky.feed.post",
        "text":      text,
        "langs":     ["en"],
        "createdAt": _now_iso(),
    }

    try:
        resp = requests.post(
            f"{BSKY_PDS}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {jwt}"},
            json={
                "repo":       did,
                "collection": "app.bsky.feed.post",
                "record":     record,
            },
            timeout=15,
        )
        return resp.status_code in (200, 201)
    except Exception:
        return False
