#!/usr/bin/env python3
"""
OSINT Agent — SENTINEL
Моніторинг глобальних військових та безпекових подій.
Запуск: python3 agent.py
Cron:   0 * * * * /usr/bin/python3 /home/vir/Documents/OSINT/agent.py
"""

import sys
import os
import json
import fcntl
import logging

# Додаємо директорію скрипту до path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import LOCK_FILE, MIN_IMPORTANCE, MAX_ALERTS_RUN, MAX_RED_DAY, MAX_YELLOW_DAY, MAX_GREEN_DAY, WP_ENABLED
from sources import collect_all
from llm import analyze_signals, rewrite_for_web
from dedup import make_hash, is_seen, mark_seen, filter_new_sources, mark_sources_seen, is_similar_to_recent, count_sent_today_by_level
from telegram_sender import send_alert, send_error_log
from wordpress import publish, is_wp_duplicate
import bluesky_sender
import mastodon_sender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("osint")



def run():
    # ── Lock: захист від паралельних запусків ──────────────────────────────
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("Попередній запуск ще виконується — пропускаємо.")
        return

    try:
        log.info("=== OSINT Agent запуск ===")

        # ── Денні ліміти по рівнях ─────────────────────────────────────────
        day_counts = {
            "RED":    count_sent_today_by_level("RED"),
            "YELLOW": count_sent_today_by_level("YELLOW"),
            "GREEN":  count_sent_today_by_level("GREEN"),
        }
        day_limits = {"RED": MAX_RED_DAY, "YELLOW": MAX_YELLOW_DAY, "GREEN": MAX_GREEN_DAY}
        # Якщо всі рівні вичерпані — виходимо
        if all(day_counts[l] >= day_limits[l] for l in day_limits):
            log.info(f"Всі денні ліміти досягнуто. Пропускаємо.")
            return

        # ── Збір даних ─────────────────────────────────────────────────────
        log.info("Збираємо дані...")
        data = collect_all()

        # Фільтруємо вже оброблені URL (перший рівень дедублікації)
        all_items = []
        for key in data:
            new_items = filter_new_sources(data[key])
            skipped = len(data[key]) - len(new_items)
            if skipped:
                log.info(f"  {key}: пропущено {skipped} вже бачених")
            data[key] = new_items
            all_items.extend(new_items)

        counts = {k: len(v) for k, v in data.items()}
        log.info(f"Нових даних: {counts}")

        total = sum(counts.values())
        if total == 0:
            log.info("Немає нових даних — завершуємо.")
            return

        # ── Аналіз LLM ─────────────────────────────────────────────────────
        log.info("Аналізуємо через LLM...")
        raw = analyze_signals(data)
        if not raw:
            log.warning("LLM не відповів або недоступний.")
            send_error_log("LLM недоступний (обидві моделі)")
            return

        # ── Парсинг JSON ────────────────────────────────────────────────────
        def _parse_alerts(raw: str) -> list | None:
            """Парсить JSON з відповіді LLM, рятує часткові об'єкти при обрізці."""
            import re as _re
            raw_clean = raw.strip()
            if "```" in raw_clean:
                raw_clean = raw_clean.split("```")[1]
                if raw_clean.startswith("json"):
                    raw_clean = raw_clean[4:]
            raw_clean = raw_clean.strip()
            # Спроба 1: повний JSON
            try:
                result = json.loads(raw_clean)
                return result if isinstance(result, list) else None
            except json.JSONDecodeError:
                pass
            # Спроба 2: JSON обрізано посередині — рятуємо повні об'єкти
            # Шукаємо всі закриті об'єкти { ... } всередині масиву
            objects = []
            depth = 0
            start = None
            in_str = False
            esc = False
            for i, ch in enumerate(raw_clean):
                if esc:
                    esc = False
                    continue
                if ch == '\\' and in_str:
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == '{':
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and start is not None:
                        try:
                            obj = json.loads(raw_clean[start:i+1])
                            if isinstance(obj, dict) and obj.get("level"):
                                objects.append(obj)
                        except Exception:
                            pass
                        start = None
            if objects:
                log.warning(f"JSON обрізано — врятовано {len(objects)} повних об'єктів")
                return objects
            return None

        alerts = _parse_alerts(raw)
        if alerts is None:
            log.error(f"JSON parse error — не вдалось врятувати.\nRaw: {raw[:300]}")
            return
        if not alerts:
            log.info("LLM повернув порожній результат.")
            return

        log.info(f"LLM знайшов {len(alerts)} сигналів")

        # ── Сортування: RED > YELLOW > GREEN, потім importance ─────────────
        level_order = {"RED": 0, "YELLOW": 1, "GREEN": 2}
        alerts.sort(key=lambda a: (
            level_order.get(a.get("level", "GREEN"), 2),
            -a.get("importance", 0)
        ))

        # ── Відправка ───────────────────────────────────────────────────────
        sent = 0
        for alert in alerts:
            if sent >= MAX_ALERTS_RUN:
                log.info(f"Досягнуто ліміт {MAX_ALERTS_RUN} постів за запуск.")
                break

            level = alert.get("level", "GREEN")
            importance = alert.get("importance", 0)
            if importance < MIN_IMPORTANCE:
                log.info(f"Пропускаємо (importance={importance}): {alert.get('title_ua','')[:50]}")
                continue

            # Денний ліміт по рівню
            if day_counts.get(level, 0) >= day_limits.get(level, 999):
                log.info(f"Ліміт {level} за добу ({day_counts[level]}). Пропускаємо.")
                continue

            title_ua = alert.get("title_ua", "")
            title_en = alert.get("title_en", "")

            h = make_hash(title_ua, title_en)
            if is_seen(h):
                log.info(f"Дублікат (hash): {title_ua[:50]}")
                continue
            if is_similar_to_recent(title_ua, title_en, level):
                log.info(f"Дублікат (семантика): {title_ua[:50]}")
                continue
            log.info(f"Відправляємо [{level}] importance={importance}: {alert.get('title_ua','')[:60]}")

            # ── RED: спочатку WordPress з зображенням, потім соцмережі з лінком ──
            if WP_ENABLED and level == "RED":
                title_ua_chk = alert.get("title_ua", "")
                if is_wp_duplicate(title_ua_chk):
                    log.info(f"  — WordPress пропущено (схожа стаття вже є): {title_ua_chk[:60]}")
                else:
                    rewritten = rewrite_for_web(alert)
                    wp_ok, wp_url = publish(rewritten)
                    if wp_ok:
                        alert = dict(rewritten)
                        alert["wp_url"] = wp_url
                    log.info(f"  {'✓' if wp_ok else '✗'} WordPress {'→ ' + wp_url if wp_ok else 'помилка'}")
            elif WP_ENABLED and level != "RED":
                log.info(f"  — WordPress пропущено (level={level})")

            # ── Соцмережі: RED із посиланням на статтю, YELLOW/GREEN — без посилань ──
            tg_ok    = send_alert(alert)
            bs_ok    = bluesky_sender.send(alert)
            masto_ok = mastodon_sender.send(alert)

            if tg_ok or bs_ok or masto_ok:
                mark_seen(h, level, alert.get("title_ua", ""))
                day_counts[level] = day_counts.get(level, 0) + 1
                if tg_ok:
                    sent += 1
                log.info(
                    f"  {'✓' if tg_ok else '✗'} TG  "
                    f"{'✓' if bs_ok else '✗'} Bluesky  "
                    f"{'✓' if masto_ok else '✗'} Mastodon"
                )
            else:
                log.error(f"  ✗ Всі платформи недоступні")

        # Позначаємо всі вхідні URL як оброблені
        mark_sources_seen(all_items)

        log.info(f"=== Завершено: відправлено {sent} сповіщень ===")

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    run()
