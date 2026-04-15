"""
OSINT Agent — збір даних із безкоштовних джерел без реєстрації
"""

import re
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from config import YACY_URL, YACY_MAX


# ── GDELT ──────────────────────────────────────────────────────────────────────

GDELT_QUERIES = [
    # Прямі зіткнення — найвищий пріоритет
    ("US Iran military clash attack",           "military"),
    ("shot down aircraft military",             "aviation+military"),
    ("war declared military offensive",         "military"),
    ("nuclear weapon threat launch",            "nuclear"),
    ("ballistic missile launch",                "military"),
    ("warship attacked sunk naval",             "naval"),
    ("civilians killed airstrike casualties",   "military"),
    ("explosion blast killed wounded",          "military"),
    # Україна / Росія
    ("missile strike ukraine Russia attack",    "aviation+military"),
    ("air defense interception Ukraine",        "aviation+military"),
    ("strategic bomber Tu-95 Tu-160 airborne",  "aviation+military"),
    # Близький Схід — детально
    ("Israel Iran attack strike",               "military"),
    ("Iran missile drone attack Saudi Arabia",  "military"),
    ("Houthi missile strike ship tanker",       "naval"),
    ("airstrike Iraq Erbil Kurdistan casualties","military"),
    ("Syria airstrike attack casualties",       "military"),
    ("Iraq explosion casualties killed",        "military"),
    ("Saudi Arabia missile drone attack",       "military"),
    ("Yemen Houthi attack strike",              "military"),
    ("Lebanon Hezbollah Israel strike",         "military"),
    # Глобальні гарячі точки
    ("Taiwan strait China military",            "military"),
    ("North Korea missile launch ICBM",         "military"),
    ("Iran nuclear enrichment IAEA",            "nuclear"),
    ("India Pakistan border clash",             "military"),
    ("Strait Hormuz blockade closure",          "naval"),
    # Сигнали підготовки
    ("troop buildup border military concentration", "military"),
    ("GPS jamming spoofing Europe",             "sigint"),
    ("cyber attack critical infrastructure",    "cyber"),
    ("emergency evacuation embassy",            "diplomatic"),
    ("martial law state emergency declared",    "diplomatic"),
    # Розвідка / попередження
    ("military escalation warning NATO",        "military"),
    ("nuclear alert warning DEFCON",            "nuclear"),
    ("submarine deployment carrier group",      "naval"),
    # Африка / інші зони
    ("Sudan civil war attack",                  "military"),
    ("Pakistan Afghanistan airstrike",          "military"),
]

def fetch_gdelt() -> list[dict]:
    """GDELT Doc API — останні 2 години, без ключа."""
    results = []
    base = "https://api.gdeltproject.org/api/v2/doc/doc"
    seen_urls = set()

    for query, category in GDELT_QUERIES:
        try:
            resp = requests.get(base, params={
                "query":      query,
                "mode":       "artlist",
                "maxrecords": "10",
                "format":     "json",
                "timespan":   "15",      # останні 15 хвилин
                "sort":       "datedesc",
            }, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for art in data.get("articles", []):
                url = art.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                results.append({
                    "source":   "gdelt",
                    "category": category,
                    "title":    art.get("title", ""),
                    "url":      url,
                    "domain":   art.get("domain", ""),
                    "date":     art.get("seendate", ""),
                    "lang":     art.get("language", ""),
                    "query":    query,
                })
        except Exception:
            pass

    return results


# ── OpenSky Network ────────────────────────────────────────────────────────────

# Зони спостереження: [lon_min, lat_min, lon_max, lat_max]
WATCH_ZONES = {
    "Eastern Europe": (22.0, 44.0, 42.0, 55.0),
    "Black Sea":      (27.0, 40.0, 42.0, 48.0),
    "Baltic Region":  (14.0, 53.0, 30.0, 60.0),
    "Kaliningrad":    (19.0, 53.5, 23.0, 56.0),
    "Belarus border": (23.0, 51.0, 33.0, 55.0),
}

# Відомі ИКАО-префікси стратегічної авіації РФ
RU_STRATEGIC_PREFIXES = ("RA-", "RF-", "RFF")
TANKER_KEYWORDS       = ("IL-78", "IL78", "A310", "KC-135")
BOMBER_KEYWORDS       = ("TU-95", "TU-160", "TU95", "TU160", "B-52")

def fetch_opensky() -> list[dict]:
    """OpenSky anonymous — аномальна авіація над зонами спостереження."""
    results = []
    base = "https://opensky-network.org/api/states/all"

    for zone_name, (lon_min, lat_min, lon_max, lat_max) in WATCH_ZONES.items():
        try:
            resp = requests.get(base, params={
                "lamin": lat_min, "lamax": lat_max,
                "lomin": lon_min, "lomax": lon_max,
            }, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            states = data.get("states", []) or []

            for s in states:
                # s[1]=callsign, s[7]=on_ground, s[9]=velocity, s[10]=heading, s[5]=lon, s[6]=lat
                callsign = (s[1] or "").strip()
                if not callsign:
                    continue
                on_ground = s[8] if len(s) > 8 else True
                if on_ground:
                    continue

                # Фільтр: тільки підозрілі борти
                is_strategic = (
                    any(callsign.startswith(p) for p in RU_STRATEGIC_PREFIXES)
                    or any(k in callsign.upper() for k in TANKER_KEYWORDS + BOMBER_KEYWORDS)
                )
                if not is_strategic:
                    continue

                results.append({
                    "source":   "opensky",
                    "category": "aviation+military",
                    "callsign": callsign,
                    "zone":     zone_name,
                    "lon":      s[5],
                    "lat":      s[6],
                    "velocity": s[9],
                    "heading":  s[10],
                    "title":    f"Стратегічний борт {callsign} у зоні {zone_name}",
                })
        except Exception:
            pass

    return results


# ── USGS Earthquakes ──────────────────────────────────────────────────────────

# Регіони де підземні вибухи можуть бути актуальними
SEISMIC_REGIONS = [
    {"name": "Ukraine/Russia theater", "minlat": 44, "maxlat": 55, "minlon": 22, "maxlon": 42},
    {"name": "Middle East",            "minlat": 25, "maxlat": 38, "minlon": 30, "maxlon": 60},
    {"name": "Korean Peninsula",       "minlat": 35, "maxlat": 43, "minlon": 124, "maxlon": 132},
]

def fetch_usgs() -> list[dict]:
    """USGS землетруси — без ключа. Mag >= 3.5, останні 2 години."""
    results = []
    base = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    now = datetime.now(timezone.utc)
    start = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")

    for region in SEISMIC_REGIONS:
        try:
            resp = requests.get(base, params={
                "format":     "geojson",
                "starttime":  start,
                "minmagnitude": "3.5",
                "minlatitude":  region["minlat"],
                "maxlatitude":  region["maxlat"],
                "minlongitude": region["minlon"],
                "maxlongitude": region["maxlon"],
                "orderby":    "time",
            }, timeout=10)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                coords = feat.get("geometry", {}).get("coordinates", [])
                results.append({
                    "source":    "usgs",
                    "category":  "seismic",
                    "region":    region["name"],
                    "place":     props.get("place", ""),
                    "magnitude": props.get("mag", 0),
                    "depth_km":  coords[2] if len(coords) > 2 else None,
                    "time_utc":  datetime.fromtimestamp(
                        props.get("time", 0) / 1000, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M UTC"),
                    "url":       props.get("url", ""),
                    "title":     f"M{props.get('mag',0)} {props.get('place','')} ({region['name']})",
                })
        except Exception:
            pass

    return results


# ── NASA EONET ────────────────────────────────────────────────────────────────

def fetch_eonet() -> list[dict]:
    """NASA EONET — теплові аномалії та надзвичайні події. Тільки зони конфліктів."""
    # Зони: [lat_min, lat_max, lon_min, lon_max]
    CONFLICT_ZONES = [
        (44.0, 55.0, 22.0, 42.0),   # Україна / Східна Європа
        (28.0, 42.0, 25.0, 60.0),   # Близький Схід / Туреччина
        (15.0, 38.0, 35.0, 60.0),   # Ірак / Іран / Саудівська Аравія
        (20.0, 40.0, 60.0, 80.0),   # Пакистан / Афганістан / Індія
        (10.0, 40.0, -20.0, 40.0),  # Африка (Сахель, Судан)
        (22.0, 42.0, 100.0, 130.0), # Азія / Тайвань / Корея
        (35.0, 45.0, 60.0, 90.0),   # Центральна Азія
    ]

    def in_conflict_zone(lat, lon):
        if lat is None or lon is None:
            return False
        for lat_min, lat_max, lon_min, lon_max in CONFLICT_ZONES:
            if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                return True
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    results = []
    try:
        resp = requests.get(
            "https://eonet.gsfc.nasa.gov/api/v3/events",
            params={"limit": 50, "status": "open", "days": 2},
            timeout=10
        )
        if resp.status_code != 200:
            return []
        for event in resp.json().get("events", []):
            geo = event.get("geometry", [{}])
            if not geo:
                continue
            # Беремо останню геометрію (найсвіжіша точка)
            last_geo = geo[-1]
            coords = last_geo.get("coordinates", [])
            lat = coords[1] if len(coords) > 1 else None
            lon = coords[0] if len(coords) > 0 else None

            # Фільтр по часу останнього оновлення
            date_str = last_geo.get("date", "")
            if date_str:
                try:
                    event_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if event_time < cutoff:
                        continue
                except Exception:
                    pass

            if not in_conflict_zone(lat, lon):
                continue
            results.append({
                "source":   "eonet",
                "category": "thermal",
                "title":    event.get("title", ""),
                "id":       event.get("id", ""),
                "link":     event.get("link", ""),
                "lat":      lat,
                "lon":      lon,
                "date":     date_str,
            })
    except Exception:
        pass
    return results


# ── RSS Feeds ─────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    # ── Світові медіа (нейтральні) ──────────────────────────────────────────────
    ("BBC Europe",   "https://feeds.bbci.co.uk/news/world/europe/rss.xml",                                    "military"),
    ("BBC World",    "https://feeds.bbci.co.uk/news/world/rss.xml",                                          "military"),
    ("Reuters",      "https://feeds.reuters.com/reuters/worldNews",                                          "military"),
    ("Al Jazeera",   "https://www.aljazeera.com/xml/rss/all.xml",                                            "military"),
    ("DW World",     "https://rss.dw.com/rdf/rss-en-world",                                                  "military"),
    ("Guardian",     "https://www.theguardian.com/world/rss",                                                "military"),
    ("Foreign Pol",  "https://foreignpolicy.com/feed/",                                                      "military"),
    ("Defense News", "https://www.defensenews.com/arc/outboundfeeds/rss/",                                   "military"),
    ("The War Zone", "https://www.thedrive.com/the-war-zone/rss",                                            "military"),
    ("Military Tim", "https://www.militarytimes.com/arc/outboundfeeds/rss/",                                 "military"),
    # ── Близький Схід / Ірак / Іран ─────────────────────────────────────────────
    ("Kurdistan 24", "https://www.kurdistan24.net/en/rss.xml",                                               "military"),
    ("Al-Monitor",   "https://www.al-monitor.com/rss",                                                       "military"),
    ("MEMO",         "https://www.middleeastmonitor.com/feed/",                                              "military"),
    ("Rudaw",        "https://www.rudaw.net/english/rss",                                                    "military"),
    ("Iraq News",    "https://shafaq.com/en/rss",                                                            "military"),
    # ── OSINT / Аналітика ────────────────────────────────────────────────────────
    ("Bellingcat",   "https://www.bellingcat.com/feed/",                                                     "military"),
    ("RUSI",         "https://www.rusi.org/rss.xml",                                                         "military"),
    ("ACLED",        "https://acleddata.com/feed/",                                                          "military"),
    ("ISW",          "https://www.understandingwar.org/rss.xml",                                             "military"),
    ("ReliefWeb",    "https://reliefweb.int/updates/rss.xml?primary_country=0&source=0&theme=4",             "military"),
    # ── Офіційні (тільки ті що реально публікують оперативні дані) ───────────────
    ("Pentagon",     "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10", "official"),
    ("IAEA",         "https://www.iaea.org/feeds/topstories.xml",                                            "official"),
    # ── Кібербезпека ─────────────────────────────────────────────────────────────
    ("CISA",         "https://www.cisa.gov/cybersecurity-advisories/all.xml",                                "cyber"),
    ("Krebs",        "https://krebsonsecurity.com/feed/",                                                    "cyber"),
    ("Recorded Fut", "https://www.recordedfuture.com/feed",                                                  "cyber"),
    ("Schneier",     "https://www.schneier.com/feed/atom/",                                                  "cyber"),
]

_RSS_DATE_FMTS = [
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S GMT",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
]

def _parse_rss_date(pub: str) -> datetime | None:
    """Парсить дату RSS у timezone-aware datetime або повертає None."""
    for fmt in _RSS_DATE_FMTS:
        try:
            dt = datetime.strptime(pub.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def fetch_rss() -> list[dict]:
    """RSS стрічки — без ключів, свіжі заголовки за останні 15 хвилин."""
    results = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=15)

    for name, url, category in RSS_FEEDS:
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "OSINT-Monitor/1.0"})
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")

            for item in items[:10]:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                pub   = item.findtext("pubDate", "")
                if not title:
                    continue
                # Фільтр за датою: пропускаємо старіші 24 годин
                if pub:
                    dt = _parse_rss_date(pub)
                    if dt and dt < cutoff:
                        continue
                results.append({
                    "source":   f"rss_{name.lower().replace(' ', '_')}",
                    "category": category,
                    "title":    title,
                    "url":      link,
                    "date":     pub,
                    "feed":     name,
                })
        except Exception:
            pass

    return results


# ── YaCy пошук ────────────────────────────────────────────────────────────────

YACY_QUERIES = [
    "world war three warning signs 2026",
    "military escalation direct confrontation",
    "nuclear threat alert warning",
    "missile launch ballistic detected",
    "Taiwan China military invasion",
    "Iran US military strike",
    "GPS jamming Europe anomaly",
    "troop buildup border mobilization",
]

def fetch_yacy() -> list[dict]:
    """YaCy P2P — пошук за темами через власний інстанс."""
    results = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    for query in YACY_QUERIES:
        try:
            resp = requests.get(YACY_URL, params={
                "query":          query,
                "maximumRecords": YACY_MAX,
                "resource":       "global",
                "contentdom":     "text",
            }, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for item in data.get("channels", [{}])[0].get("items", []):
                pub = item.get("pubDate", "")
                # Фільтр за датою: пропускаємо старіші 24 годин
                if pub:
                    dt = _parse_rss_date(pub)
                    if dt and dt < cutoff:
                        continue
                results.append({
                    "source":   "yacy",
                    "category": "web",
                    "title":    item.get("title", ""),
                    "url":      item.get("link", ""),
                    "date":     pub,
                    "query":    query,
                })
        except Exception:
            pass
    return results


# ── GDACS — глобальні катастрофи (землетруси, циклони, повені, вулкани) ──────

def fetch_gdacs() -> list[dict]:
    """GDACS RSS — офіційні попередження про природні катастрофи."""
    results = []
    try:
        resp = requests.get(
            "https://www.gdacs.org/xml/rss.xml",
            timeout=15, headers={"User-Agent": "OSINT-Monitor/1.0"}
        )
        if resp.status_code != 200:
            return results
        root = ET.fromstring(resp.content)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=48)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            pub   = item.findtext("pubDate", "")
            if not title:
                continue
            if pub:
                dt = _parse_rss_date(pub)
                if dt and dt < cutoff:
                    continue
            # GDACS має alertlevel в namespace — витягуємо з title
            results.append({
                "source":   "gdacs",
                "category": "disaster",
                "title":    title,
                "url":      link,
                "date":     pub,
            })
    except Exception:
        pass
    return results


# ── OREF — сирени цивільного захисту Ізраїлю (реальний час) ──────────────────

def fetch_oref() -> list[dict]:
    """OREF API — активні тривоги в Ізраїлі. Порожньо = тихо."""
    results = []
    try:
        resp = requests.get(
            "https://www.oref.org.il/WarningMessages/History/AlertsHistory.json",
            timeout=10,
            headers={
                "User-Agent": "OSINT-Monitor/1.0",
                "Referer":    "https://www.oref.org.il/",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        if resp.status_code != 200 or not resp.text.strip():
            return results
        alerts = resp.json()
        if not isinstance(alerts, list):
            return results
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=15)
        for alert in alerts[:20]:
            date_str = alert.get("alertDate", "")
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
            cities = alert.get("data", "")
            title  = f"OREF Alert: {alert.get('title','rocket/missile')} — {cities}"
            results.append({
                "source":   "oref",
                "category": "military",
                "title":    title,
                "url":      "https://www.oref.org.il/",
                "date":     date_str,
            })
    except Exception:
        pass
    return results


# ── UCDP — Uppsala Conflict Data Program (академічна база подій конфліктів) ───

def fetch_ucdp() -> list[dict]:
    """UCDP Candidate Events — верифіковані бойові події за останні 30 днів."""
    results = []
    try:
        resp = requests.get(
            "https://ucdpapi.pcr.uu.se/api/gedevents/23.1",
            params={"pagesize": 20, "page": 1},
            timeout=15, headers={"User-Agent": "OSINT-Monitor/1.0"}
        )
        if resp.status_code != 200:
            return results
        data = resp.json()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)
        for ev in data.get("Result", []):
            date_str = ev.get("date_start", "")
            try:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
            country  = ev.get("country", "")
            deaths   = ev.get("best", 0)
            conflict = ev.get("conflict_name", "")
            title    = f"UCDP: {conflict} [{country}] — {deaths} casualties"
            results.append({
                "source":   "ucdp",
                "category": "military",
                "title":    title,
                "url":      f"https://ucdp.uu.se/event/{ev.get('id','')}",
                "date":     date_str,
                "deaths":   deaths,
            })
    except Exception:
        pass
    return results


# ── Cloudflare Radar — інтернет-збої та атаки по країнах ─────────────────────

def fetch_cloudflare_radar() -> list[dict]:
    """Cloudflare Radar RSS — збої, BGP аномалії, DDoS атаки."""
    results = []
    try:
        resp = requests.get(
            "https://blog.cloudflare.com/tag/cloudflare-radar/rss/",
            timeout=10, headers={"User-Agent": "OSINT-Monitor/1.0"}
        )
        if resp.status_code != 200:
            return results
        root = ET.fromstring(resp.content)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=72)
        for item in root.findall(".//item")[:5]:
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            pub   = item.findtext("pubDate", "")
            if not title:
                continue
            if pub:
                dt = _parse_rss_date(pub)
                if dt and dt < cutoff:
                    continue
            results.append({
                "source":   "cloudflare_radar",
                "category": "cyber",
                "title":    title,
                "url":      link,
                "date":     pub,
            })
    except Exception:
        pass
    return results


# ── Telegram Public Channels (web preview, без API) ───────────────────────────

# Канали OSINT/military що мають публічний веб-перегляд t.me/s/channel
TG_CHANNELS = [
    ("wfwitness",            "military"),
    ("war_monitor",          "military"),   # War&Famine Witness — breaking events з відео
    ("GeoConfirmed",         "military"),   # Геолокація та підтвердження подій
    ("intelslava",           "military"),   # Intel з різних джерел
    ("rybar",                "military"),   # Військова аналітика
    ("CIT_en",               "military"),   # Conflict Intelligence Team EN
    ("DefMon3",              "military"),
    ("raketa_trevoga",       "military"),
]

def fetch_telegram_channels() -> list[dict]:
    """
    Скрапінг публічних Telegram каналів через t.me/s/channel (без API ключа).
    Повертає повідомлення за останні 2 години.
    """
    results = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=15)

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    for channel, category in TG_CHANNELS:
        try:
            resp = requests.get(
                f"https://t.me/s/{channel}",
                headers=headers,
                timeout=15
            )
            if resp.status_code != 200:
                continue

            html = resp.text

            # Витягуємо блоки повідомлень: текст між тегами message
            # Формат: <div class="tgme_widget_message_text...">...</div>
            # і дата <time datetime="2026-04-07T10:05:00+00:00">
            texts = re.findall(
                r'<div[^>]+class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                html, re.DOTALL
            )
            dates = re.findall(
                r'<time[^>]+datetime="([^"]+)"',
                html
            )

            for i, raw_text in enumerate(texts):
                # Очищаємо HTML теги
                text = re.sub(r'<[^>]+>', '', raw_text).strip()
                text = re.sub(r'\s+', ' ', text)
                if len(text) < 20:
                    continue

                # Дата
                date_str = dates[i] if i < len(dates) else ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt < cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass

                # Беремо перший рядок як заголовок
                title = text[:120].split("\n")[0].strip()
                if not title:
                    continue

                # Унікальний URL для кожного повідомлення (хеш тексту+дати)
                msg_hash = hashlib.md5(f"{channel}{date_str}{text[:100]}".encode()).hexdigest()[:12]
                results.append({
                    "source":   f"telegram_{channel}",
                    "category": category,
                    "title":    f"[{channel}] {title}",
                    "url":      f"https://t.me/{channel}#{msg_hash}",
                    "date":     date_str,
                    "feed":     f"TG @{channel}",
                    "body":     text[:500],
                })
        except Exception:
            continue

    return results


# ── Головна функція ───────────────────────────────────────────────────────────

def collect_all() -> dict:
    """Зібрати всі дані паралельно (послідовно для простоти)."""
    return {
        "gdelt":            fetch_gdelt(),
        "opensky":          fetch_opensky(),
        "usgs":             fetch_usgs(),
        "eonet":            fetch_eonet(),
        "gdacs":            fetch_gdacs(),
        "oref":             fetch_oref(),
        "ucdp":             fetch_ucdp(),
        "cloudflare_radar": fetch_cloudflare_radar(),
        "rss":              fetch_rss(),
        "telegram":         fetch_telegram_channels(),
    }
