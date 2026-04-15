"""
OSINT Agent — конфігурація з environment variables
"""

import os


def _req(name: str) -> str:
    """Обов'язкова змінна — падає з чітким повідомленням якщо відсутня."""
    val = os.environ.get(name)
    if not val:
        raise EnvironmentError(f"Required environment variable not set: {name}")
    return val


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ── Telegram — публічний канал ────────────────────────────
TG_BOT_TOKEN    = _req("TG_BOT_TOKEN")
TG_CHAT_ID      = int(_req("TG_CHAT_ID"))
TG_THREAD_ID    = int(_opt("TG_THREAD_ID", "0") or "0")

# ── Telegram — адмін (помилки, діагностика) ───────────────
_admin_chat = _opt("ADMIN_CHAT_ID")
ADMIN_CHAT_ID   = int(_admin_chat) if _admin_chat else None
_admin_thread = _opt("ADMIN_THREAD_ID")
ADMIN_THREAD_ID = int(_admin_thread) if _admin_thread else None

# ── DeepSeek API ──────────────────────────────────────────
DEEPSEEK_API_KEY = _req("DEEPSEEK_API_KEY")
DEEPSEEK_URL     = _opt("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions")
DEEPSEEK_MODEL   = _opt("DEEPSEEK_MODEL", "deepseek-chat")
LLM_TEMPERATURE  = float(_opt("LLM_TEMPERATURE", "0.0"))
LLM_MAX_TOKENS   = int(_opt("LLM_MAX_TOKENS", "8000"))

# ── YaCy пошук ────────────────────────────────────────────
YACY_URL        = _opt("YACY_URL", "https://search.newsgroup.site/yacysearch.json")
YACY_MAX        = int(_opt("YACY_MAX", "6"))

# ── Стан / дедублікація ───────────────────────────────────
DB_PATH         = _opt("DB_PATH", "/data/dedup.db")
LOCK_FILE       = _opt("LOCK_FILE", "/tmp/osint_agent.lock")
LOG_PATH        = _opt("LOG_PATH", "/data/agent.log")

# ── Порогові значення ─────────────────────────────────────
MIN_IMPORTANCE  = int(_opt("MIN_IMPORTANCE", "1"))
MAX_ALERTS_RUN  = int(_opt("MAX_ALERTS_RUN", "3"))
MAX_RED_DAY     = int(_opt("MAX_RED_DAY", "150"))
MAX_YELLOW_DAY  = int(_opt("MAX_YELLOW_DAY", "80"))
MAX_GREEN_DAY   = int(_opt("MAX_GREEN_DAY", "15"))

# ── WordPress ─────────────────────────────────────────────
WP_URL          = _opt("WP_URL", "https://newsgroup.site/wp-json/wp/v2/posts")
WP_USER         = _req("WP_USER")
WP_APP_PASSWORD = _req("WP_APP_PASSWORD")
WP_CATEGORY_ID  = int(_opt("WP_CATEGORY_ID", "505"))
WP_ENABLED      = _opt("WP_ENABLED", "true").lower() in ("1", "true", "yes")

# ── Pexels (зображення для статей) ────────────────────────
PEXELS_API_KEY  = _opt("PEXELS_API_KEY", "")

# ── Bluesky ───────────────────────────────────────────────
BS_HANDLE       = _opt("BS_HANDLE", "")
BS_APP_PASSWORD = _opt("BS_APP_PASSWORD", "")
BS_ENABLED      = _opt("BS_ENABLED", "true").lower() in ("1", "true", "yes")

# ── Mastodon ──────────────────────────────────────────────
MASTO_INSTANCE  = _opt("MASTO_INSTANCE", "https://social.vir.group/")
MASTO_TOKEN     = _req("MASTO_TOKEN")
MASTO_ENABLED   = _opt("MASTO_ENABLED", "true").lower() in ("1", "true", "yes")
