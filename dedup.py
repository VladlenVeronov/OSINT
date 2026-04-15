"""
OSINT Agent — дедублікація через SQLite
Два рівні: source URLs (вхідні дані) + alert titles (LLM вихід)
"""

import sqlite3
import hashlib
import re
from config import DB_PATH


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_alerts (
            hash       TEXT PRIMARY KEY,
            level      TEXT,
            title      TEXT,
            sent_at    DATETIME DEFAULT (datetime('now', 'localtime'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS seen_sources (
            url        TEXT PRIMARY KEY,
            seen_at    DATETIME DEFAULT (datetime('now', 'localtime'))
        )
    """)
    # Чистимо старіші 3 дні для sources (новини швидко старіють)
    c.execute("DELETE FROM seen_sources  WHERE seen_at < datetime('now', 'localtime', '-3 days')")
    # Чистимо старіші 7 днів для alerts
    c.execute("DELETE FROM sent_alerts   WHERE sent_at < datetime('now', 'localtime', '-7 days')")
    c.commit()
    return c


# ── Дедублікація вхідних джерел (URL-рівень) ──────────────────────────────────

def filter_new_sources(items: list[dict]) -> list[dict]:
    """Повертає тільки ті items, чий url ще не бачили."""
    if not items:
        return []
    c = _conn()
    result = []
    for item in items:
        url = item.get("url", "").strip()
        if not url:
            result.append(item)  # без URL — пропускаємо через
            continue
        row = c.execute("SELECT 1 FROM seen_sources WHERE url=?", (url,)).fetchone()
        if not row:
            result.append(item)
    c.close()
    return result


def mark_sources_seen(items: list[dict]):
    """Позначаємо URL як оброблені."""
    c = _conn()
    for item in items:
        url = item.get("url", "").strip()
        if url:
            c.execute("INSERT OR IGNORE INTO seen_sources (url) VALUES (?)", (url,))
    c.commit()
    c.close()


# ── Дедублікація вихідних алертів (title-рівень) ──────────────────────────────

# Стоп-слова: прибираємо загальні слова що не несуть унікального змісту
_STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "to", "of", "and", "or", "is", "was",
    "are", "were", "for", "with", "by", "from", "as", "into", "that", "this",
    "has", "have", "had", "be", "been", "will", "would", "could", "should",
    "over", "after", "before", "between", "against", "during", "near", "new",
    # Українські
    "у", "в", "на", "до", "з", "за", "по", "при", "та", "і", "й", "або",
    "що", "як", "це", "він", "вона", "вони", "їх", "його", "після", "через",
}

def _normalize(text: str) -> str:
    """Прибираємо стоп-слова, цифри, пунктуацію — лишаємо ключові слова події."""
    text = text.lower().strip()
    text = re.sub(r'\d+', '', text)          # цифри
    text = re.sub(r'[^\w\s]', '', text)      # пунктуація
    words = [w for w in text.split() if w not in _STOP_WORDS and len(w) > 2]
    # Сортуємо слова — порядок не має значення для дедуп (різне формулювання)
    words.sort()
    return " ".join(words[:12])              # перші 12 ключових слів


def make_hash(title_ua: str, title_en: str) -> str:
    """Стабільний хеш тільки по заголовках (тіло LLM змінює)."""
    text = _normalize(title_ua) + "|" + _normalize(title_en)
    return hashlib.md5(text.encode()).hexdigest()


def is_seen(h: str) -> bool:
    c = _conn()
    row = c.execute("SELECT 1 FROM sent_alerts WHERE hash=?", (h,)).fetchone()
    c.close()
    return row is not None


def mark_seen(h: str, level: str, title: str):
    c = _conn()
    c.execute(
        "INSERT OR IGNORE INTO sent_alerts (hash, level, title) VALUES (?,?,?)",
        (h, level, title)
    )
    c.commit()
    c.close()


def is_similar_to_recent(title_ua: str, title_en: str, level: str = "GREEN") -> bool:
    """Семантична дедублікація з вікном залежно від рівня:
    RED   — 30 хв (постійно оновлюється)
    YELLOW— 2 год
    GREEN — 12 год
    """
    windows = {"RED": "-30 minutes", "YELLOW": "-2 hours", "GREEN": "-12 hours"}
    window = windows.get(level, "-2 hours")
    threshold = 0.60

    new_words = set(_normalize(title_ua).split()) | set(_normalize(title_en).split())
    if not new_words:
        return False
    c = _conn()
    rows = c.execute(
        f"SELECT title FROM sent_alerts WHERE sent_at > datetime('now', 'localtime', '{window}')"
    ).fetchall()
    c.close()
    for (existing_title,) in rows:
        existing_words = set(_normalize(existing_title).split())
        if not existing_words:
            continue
        overlap = len(new_words & existing_words) / min(len(new_words), len(existing_words))
        if overlap >= threshold:
            return True
    return False


def count_sent_today_by_level(level: str) -> int:
    """Скільки алертів певного рівня відправлено за поточну добу."""
    c = _conn()
    row = c.execute(
        "SELECT COUNT(*) FROM sent_alerts WHERE level=? AND sent_at > datetime('now', 'localtime', 'start of day')",
        (level,)
    ).fetchone()
    c.close()
    return row[0] if row else 0
