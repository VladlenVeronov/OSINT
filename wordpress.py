"""
OSINT Agent — публікація на WordPress (без пошуку зображень)
"""

import re
import logging
import requests
from base64 import b64encode
from config import WP_URL, WP_USER, WP_APP_PASSWORD, WP_CATEGORY_ID, WP_ENABLED

log = logging.getLogger("osint")

LEVEL_EMOJI = {"RED": "🔴", "YELLOW": "🟡", "GREEN": "🟢"}


SOCIAL_SHARING_BLOCK = """
<!-- wp:outermost/social-sharing {"size":"has-large-icon-size"} -->
<ul class="wp-block-outermost-social-sharing has-large-icon-size"><!-- wp:outermost/social-sharing-link {"service":"bluesky"} /-->

<!-- wp:outermost/social-sharing-link {"service":"facebook"} /-->

<!-- wp:outermost/social-sharing-link {"service":"linkedin"} /-->

<!-- wp:outermost/social-sharing-link {"service":"mail"} /-->

<!-- wp:outermost/social-sharing-link {"service":"print"} /-->

<!-- wp:outermost/social-sharing-link {"service":"reddit"} /-->

<!-- wp:outermost/social-sharing-link {"service":"tumblr"} /-->

<!-- wp:outermost/social-sharing-link {"service":"whatsapp"} /-->

<!-- wp:outermost/social-sharing-link {"service":"viber"} /-->

<!-- wp:outermost/social-sharing-link {"service":"threads"} /-->

<!-- wp:outermost/social-sharing-link {"service":"telegram"} /-->

<!-- wp:outermost/social-sharing-link {"service":"x"} /--></ul>
<!-- /wp:outermost/social-sharing -->

<!-- wp:paragraph -->
<p></p>
<!-- /wp:paragraph -->
""".strip()

# Транслітерація UA → Latin для slug
_TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'h','ґ':'g','д':'d','е':'e','є':'ye',
    'ж':'zh','з':'z','и':'y','і':'i','ї':'yi','й':'y','к':'k','л':'l',
    'м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u',
    'ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ь':'',
    'ю':'yu','я':'ya',
}

def _transliterate(text: str) -> str:
    result = []
    for ch in text.lower():
        if ch in _TRANSLIT:
            result.append(_TRANSLIT[ch])
        elif ch.isascii() and (ch.isalnum() or ch == ' '):
            result.append(ch)
        else:
            result.append('-')
    slug = re.sub(r'-+', '-', ''.join(result)).strip('-')
    return slug[:60]


def _auth_header() -> dict:
    token = b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _get_or_create_tags(tag_names: list[str]) -> list[int]:
    """Повертає список tag_id з WP, створює якщо немає."""
    base = WP_URL.replace("/posts", "/tags")
    ids = []
    for name in tag_names:
        name = name.strip().lstrip('#')
        if not name:
            continue
        try:
            r = requests.get(base, params={"search": name}, headers=_auth_header(), timeout=10)
            found = [t for t in r.json() if isinstance(t, dict) and t.get("name","").lower() == name.lower()]
            if found:
                ids.append(found[0]["id"])
            else:
                r2 = requests.post(base, json={"name": name}, headers=_auth_header(), timeout=10)
                if r2.status_code in (200, 201):
                    ids.append(r2.json()["id"])
        except Exception:
            pass
    return ids


def _flag(code: str) -> str:
    code = code.upper().strip()
    if len(code) == 2 and code.isalpha():
        return chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)
    return ""


def _country_flags(countries: list) -> str:
    flags = [_flag(c) for c in (countries or [])[:3] if _flag(c)]
    return " ".join(flags)


def format_wp_post(alert: dict) -> dict:
    level         = alert.get("level", "GREEN")
    icon          = LEVEL_EMOJI.get(level, "🟢")
    imp           = alert.get("importance", 1)
    alert_type    = alert.get("type", "")
    country_flags = _country_flags(alert.get("countries", []))
    note          = alert.get("note", "")

    title_ua      = alert.get("title_ua", "")
    body_ua       = alert.get("body_ua", "")
    conclusion_ua = alert.get("conclusion_ua", "")
    title_en      = alert.get("title_en", "")
    body_en       = alert.get("body_en", "")
    conclusion_en = alert.get("conclusion_en", "")

    excerpt = ". ".join(body_ua.split(". ")[:2]).strip()
    slug = _transliterate(title_ua)

    note_html = f"""
<!-- wp:quote -->
<blockquote class="wp-block-quote"><!-- wp:paragraph -->
<p>💬 {note}</p>
<!-- /wp:paragraph --></blockquote>
<!-- /wp:quote -->""" if note else ""

    conclusion_ua_html = f"""
<!-- wp:paragraph -->
<p><em>Висновок: {conclusion_ua}</em></p>
<!-- /wp:paragraph -->""" if conclusion_ua else ""

    conclusion_en_html = f"""
<!-- wp:paragraph -->
<p><em>Conclusion: {conclusion_en}</em></p>
<!-- /wp:paragraph -->""" if conclusion_en else ""

    content = f"""<!-- wp:paragraph -->
<p>{icon} {alert_type} | {imp}/10{" " + country_flags if country_flags else ""}</p>
<!-- /wp:paragraph -->

<!-- wp:heading {{"level":3}} -->
<h3>{title_ua}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{body_ua}</p>
<!-- /wp:paragraph -->
{conclusion_ua_html}

<!-- wp:separator -->
<hr class="wp-block-separator"/>
<!-- /wp:separator -->

<!-- wp:heading {{"level":3}} -->
<h3>{title_en}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{body_en}</p>
<!-- /wp:paragraph -->
{conclusion_en_html}
{note_html}

{SOCIAL_SHARING_BLOCK}"""

    return {
        "title":   title_ua,
        "content": content,
        "excerpt": excerpt,
        "slug":    slug,
    }


def _normalize_title(text: str) -> set:
    """Нормалізація заголовку для порівняння — ключові слова без стоп-слів."""
    import re as _re
    _STOP = {
        "a","an","the","in","on","at","to","of","and","or","is","was","are","were",
        "for","with","by","from","as","that","this","has","have","had","be","been",
        "will","would","could","should","over","after","before","against","during",
        "у","в","на","до","з","за","по","при","та","і","й","або","що","як","це",
        "він","вона","вони","їх","його","після","через","між","над","під",
    }
    text = text.lower()
    text = _re.sub(r'\d+', '', text)
    text = _re.sub(r'[^\w\s]', '', text)
    words = [w for w in text.split() if w not in _STOP and len(w) > 2]
    return set(words[:15])


def get_recent_wp_titles(count: int = 30) -> list[str]:
    """Отримує заголовки останніх WP постів категорії OSINT."""
    try:
        media_url = WP_URL + f"?categories={WP_CATEGORY_ID}&per_page={count}&_fields=title"
        resp = requests.get(media_url, headers=_auth_header(), timeout=10)
        if resp.status_code == 200:
            return [p["title"]["rendered"] for p in resp.json() if isinstance(p, dict)]
    except Exception:
        pass
    return []


def is_wp_duplicate(title_ua: str, threshold: float = 0.50) -> bool:
    """Повертає True якщо схожа стаття вже є на сайті (50%+ спільних ключових слів)."""
    new_words = _normalize_title(title_ua)
    if not new_words:
        return False
    existing_titles = get_recent_wp_titles()
    for t in existing_titles:
        existing_words = _normalize_title(t)
        if not existing_words:
            continue
        overlap = len(new_words & existing_words) / min(len(new_words), len(existing_words))
        if overlap >= threshold:
            return True
    return False


def publish(alert: dict) -> tuple[bool, str]:
    """
    Публікує alert як WP пост без зображення.
    Повертає (True, post_url) якщо успішно, (False, '') якщо помилка.
    """
    if not WP_ENABLED:
        return False, ""

    post_data = format_wp_post(alert)
    raw_tags  = alert.get("tags", [])
    tag_ids   = _get_or_create_tags(raw_tags)

    # ── SEO meta ──────────────────────────────────────────────────────────────
    meta_description = alert.get("meta_description", post_data["excerpt"][:155])
    keywords         = alert.get("keywords", ", ".join(raw_tags[:7]))

    meta_fields = {
        "mwseo_description": meta_description,
        "mwseo_keywords":    keywords,
        "_yoast_wpseo_metadesc":  meta_description,
        "_yoast_wpseo_focuskw":   keywords.split(",")[0].strip() if keywords else "",
        "rank_math_description":  meta_description,
        "rank_math_focus_keyword": keywords.split(",")[0].strip() if keywords else "",
    }

    payload = {
        "title":      post_data["title"],
        "content":    post_data["content"],
        "excerpt":    post_data["excerpt"],
        "slug":       post_data["slug"],
        "status":     "publish",
        "categories": [WP_CATEGORY_ID],
        "tags":       tag_ids,
        "meta":       meta_fields,
    }

    try:
        resp = requests.post(
            WP_URL,
            json=payload,
            headers=_auth_header(),
            timeout=45,
        )
        if resp.status_code in (200, 201):
            post_url = resp.json().get("link", "")
            return True, post_url
        log.error(f"  WP post HTTP {resp.status_code}: {resp.text[:300]}")
        return False, ""
    except Exception as e:
        log.error(f"  WP post exception: {e}")
        return False, ""
