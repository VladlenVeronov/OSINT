"""
OSINT Agent — LLM wrapper (DeepSeek API)
"""

import json
import logging
import os
import requests
from datetime import datetime, timezone
from config import DEEPSEEK_API_KEY, DEEPSEEK_URL, DEEPSEEK_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS

log = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT = open(os.path.join(_DIR, "osint_agent_prompt.md")).read()


def ask_llm(user_message: str) -> str | None:
    """Запит через DeepSeek API. Повертає текст відповіді або None."""
    try:
        resp = requests.post(
            DEEPSEEK_URL,
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                "temperature": LLM_TEMPERATURE,
                "max_tokens":  LLM_MAX_TOKENS,
                "stream":      False,
            },
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type":  "application/json",
            },
            timeout=120,
        )
        if resp.status_code != 200:
            log.warning(f"DeepSeek API HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content:
            log.info(f"DeepSeek відповів ({len(content)} символів)")
            return content
        log.warning("DeepSeek: порожня відповідь")
    except Exception as e:
        log.warning(f"DeepSeek exception: {e}")
    return None


def analyze_signals(data: dict) -> str | None:
    """
    Передає зібрані сигнали LLM для аналізу.
    Повертає JSON-рядок зі списком alerts.
    """
    summary_parts = []

    # ── ПРІОРИТЕТ 1: Telegram (найшвидше, реальний час) ──────────────────────
    telegram = data.get("telegram", [])
    if telegram:
        lines = [f"  [{a['feed']}] {a.get('body', a['title'])[:300]}" for a in telegram[:50]]
        summary_parts.append("=== ⚡ TELEGRAM (реальний час, НАЙВИЩИЙ ПРІОРИТЕТ) ===\n" + "\n".join(lines))

    # ── ПРІОРИТЕТ 2: Ізраїльські тривоги (OREF) ──────────────────────────────
    oref = data.get("oref", [])
    if oref:
        lines = [f"  {e['title']}" for e in oref[:10]]
        summary_parts.append("=== ⚡ ТРИВОГИ ІЗРАЇЛЬ (OREF) ===\n" + "\n".join(lines))

    # ── ПРІОРИТЕТ 3: GDELT новини ────────────────────────────────────────────
    gdelt = data.get("gdelt", [])
    if gdelt:
        titles = [f"  [{a['category']}] {a['title']} ({a['domain']}) [date:{a.get('date','')}]" for a in gdelt[:20]]
        summary_parts.append("=== GDELT NEWS (останні 2год) ===\n" + "\n".join(titles))

    # ── ПРІОРИТЕТ 4: RSS стрічки ─────────────────────────────────────────────
    rss = data.get("rss", [])
    if rss:
        lines = [f"  [{a['feed']}] {a['title']}" for a in rss[:20]]
        summary_parts.append("=== RSS СТРІЧКИ ===\n" + "\n".join(lines))

    # ── Додаткові сигнали ────────────────────────────────────────────────────
    opensky = data.get("opensky", [])
    if opensky:
        lines = [f"  {a['callsign']} у {a['zone']} (v={a['velocity']} m/s, hdg={a['heading']})" for a in opensky]
        summary_parts.append("=== АВІАЦІЯ (OpenSky) ===\n" + "\n".join(lines))

    usgs = data.get("usgs", [])
    if usgs:
        lines = [f"  M{e['magnitude']} {e['place']} глибина={e['depth_km']}км {e['time_utc']}" for e in usgs]
        summary_parts.append("=== СЕЙСМІКА (USGS) ===\n" + "\n".join(lines))

    eonet = data.get("eonet", [])
    if eonet:
        lines = [f"  {e['title']}" for e in eonet[:10]]
        summary_parts.append("=== ТЕПЛОВІ АНОМАЛІЇ (EONET) ===\n" + "\n".join(lines))

    gdacs = data.get("gdacs", [])
    if gdacs:
        lines = [f"  {e['title']}" for e in gdacs[:10]]
        summary_parts.append("=== КАТАСТРОФИ (GDACS) ===\n" + "\n".join(lines))

    ucdp = data.get("ucdp", [])
    if ucdp:
        lines = [f"  {e['title']}" for e in ucdp[:10]]
        summary_parts.append("=== КОНФЛІКТИ (UCDP) ===\n" + "\n".join(lines))

    cloudflare_radar = data.get("cloudflare_radar", [])
    if cloudflare_radar:
        lines = [f"  {e['title']}" for e in cloudflare_radar[:5]]
        summary_parts.append("=== ІНТЕРНЕТ-ЗБОЇ (Cloudflare Radar) ===\n" + "\n".join(lines))

    if not summary_parts:
        return None

    raw_data = "\n\n".join(summary_parts)
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    prompt = f"""ЧАС: {current_date}. Трамп — чинний президент США.

ДЖЕРЕЛА (пріоритет): ⚡ TELEGRAM (реальний час) >> OREF >> GDELT >> RSS >> решта.
Telegram — найшвидше джерело, аналізуй першим. Якщо Telegram повідомляє про подію — це пріоритет над усіма іншими джерелами.
Telegram "unconfirmed" + конкретна локація + тип атаки = YELLOW мінімум.
Telegram підтверджена атака / тривога / вибухи = RED.

{raw_data}

---
Відповідь: ТІЛЬКИ JSON масив (без markdown). Максимум 5 елементів. Якщо нічого важливого — [].

Поля кожного елемента:
{{"level":"RED"|"YELLOW"|"GREEN","importance":1-10,"type":"тип англійською","countries":["XX"],"title_ua":"...","title_en":"...","body_ua":"1-3 речення українською","body_en":"1-3 sentences in English","note":"1 речення SENTINEL","tags":["#Tag1","#Tag2","#Tag3"],"source_url":"url або ''"}}

ВАЖЛИВО: body_ua та body_en — реальний текст з даних, НЕ шаблон ("1 речення UA" заборонено). Для атак/тривог — коротко і чітко. Для аналітики — до 3 речень.

РІВНІ (обов'язково):
🔴 RED: будь-яка атака дронами/ракетами на Україну, повітряна тривога, обстріл, вибухи — ЗАВЖДИ RED.
🟡 YELLOW: підтверджені жертви/руйнування що вже скінчились, переміщення військ, аномалії.
🟢 GREEN: заяви, дипломатія, аналітика.

РІВНІ:
🔴 RED = АКТИВНА ЗАГРОЗА ЖИТТЮ ЗАРАЗ: тривога, обстріл/удар в процесі, ракети летять, евакуація під загрозою. Все що вимагає дій прямо зараз.
🟡 YELLOW = ПІДТВЕРДЖЕНІ НАСЛІДКИ (вже скінчилось): влучання підтверджено, жертви, руйнування — але загроза минула. Також: незвичайні переміщення флоту/авіації, GPS-спуфінг.
🟢 GREEN = ІНФОРМАТИВНО: заяви, риторика, переговори, аналіз, дипломатія без дій.

ЗАБОРОНИ: RED/YELLOW для заяв посадовців → тільки GREEN. Без власних знань — тільки з вхідних даних. Теги — тільки англійською. ЗАБОРОНЕНО вигадувати або змінювати дати — використовуй тільки дати що є у вхідних даних (поле date:). Якщо дата невідома — не пиши її взагалі. ІГНОРУВАТИ: тропічні циклони, природні пожежі, повені, землетруси та будь-які природні катастрофи що НЕ пов'язані з воєнними діями або зонами конфлікту — це не OSINT, не включати у відповідь.
"""
    return ask_llm(prompt)


def rewrite_for_web(alert: dict) -> dict:
    """
    Рерайт body_ua/body_en для публікації на сайті.
    Також генерує meta_description та keywords для SEO.
    """
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prompt = f"""ПОТОЧНА ДАТА: {current_date}. Дональд Трамп — чинний президент США (з 20 січня 2025).

Зроби рерайт наступного OSINT-матеріалу для публікації на новинному сайті.

Заголовок UA: {alert.get('title_ua','')}
Заголовок EN: {alert.get('title_en','')}
Текст UA: {alert.get('body_ua','')}
Текст EN: {alert.get('body_en','')}
Висновок UA: {alert.get('conclusion_ua','')}
Висновок EN: {alert.get('conclusion_en','')}
Теги: {', '.join(alert.get('tags', []))}

Правила:
- Перефразуй ТІЛЬКИ те що вже є в тексті — жодних нових фактів
- ЗАБОРОНЕНО змінювати імена, посади, числа, дати
- body_ua: мінімум 5 речень ВИКЛЮЧНО УКРАЇНСЬКОЮ, журналістський стиль, без посилань на джерела
- body_en: minimum 5 sentences in English, journalistic style, no source references
- conclusion_ua та conclusion_en: лишити як є або злегка перефразувати
- meta_description: 140-155 символів українською, стислий опис події для Google
- keywords: 5-7 ключових слів/фраз через кому (суміш UA+EN), найбільш пошукові
- Відповідай ВИКЛЮЧНО JSON без markdown:
{{"body_ua": "...", "body_en": "...", "conclusion_ua": "...", "conclusion_en": "...", "meta_description": "...", "keywords": "..."}}"""

    raw = ask_llm(prompt)
    if not raw:
        return alert

    try:
        raw_clean = raw.strip()
        if "```" in raw_clean:
            raw_clean = raw_clean.split("```")[1]
            if raw_clean.startswith("json"):
                raw_clean = raw_clean[4:]
        rewritten = json.loads(raw_clean.strip())
        alert = dict(alert)
        for field in ("body_ua", "body_en", "conclusion_ua", "conclusion_en",
                      "meta_description", "keywords"):
            if rewritten.get(field):
                alert[field] = rewritten[field]
    except Exception:
        pass

    return alert
