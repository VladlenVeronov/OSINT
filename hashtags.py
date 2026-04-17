"""
Hashtag normalization and platform-specific tag building.

Rules per platform:
  Telegram  — 3-5 tags, CamelCase, #OSINT always, #Breaking on RED
  Bluesky   — 2-3 tags (post is short), CamelCase, #OSINT always
  Mastodon  — 4-6 tags, CamelCase, #OSINT + #NewsGroup always (hashtags = primary discovery)
"""

import re

# Static base tags per platform (always appended, deduped)
_BASE = {
    "telegram": ["#OSINT"],
    "bluesky":  ["#OSINT"],
    "mastodon": ["#OSINT", "#NewsGroup"],
}

_LIMITS = {
    "telegram": 5,
    "bluesky":  3,
    "mastodon": 6,
}

# Curated single-word replacements for common multi-word LLM outputs
_REPLACEMENTS = {
    "breaking news":        "Breaking",
    "air alert":            "AirAlert",
    "aerial attack":        "AerialAttack",
    "drone attack":         "DroneAttack",
    "missile attack":       "MissileAttack",
    "missile strike":       "MissileStrike",
    "military conflict":    "Military",
    "military operation":   "Military",
    "cyber attack":         "CyberAttack",
    "cyber security":       "CyberSecurity",
    "human rights":         "HumanRights",
    "world news":           "WorldNews",
    "breaking":             "Breaking",
    "geopolitics":          "Geopolitics",
    "ukraine war":          "Ukraine",
    "russia ukraine":       "Ukraine",
    "united states":        "USA",
    "middle east":          "MiddleEast",
    "north korea":          "NorthKorea",
    "south korea":          "SouthKorea",
    "nuclear threat":       "NuclearThreat",
    "open source":          "OSINT",
}


def _to_camel(text: str) -> str:
    """Convert 'some_tag' or 'some tag' → 'SomeTag'."""
    parts = re.split(r"[\s_\-]+", text.strip())
    return "".join(p.capitalize() for p in parts if p)


def normalize(tag: str) -> str:
    """
    Normalize one tag to a valid single-word CamelCase hashtag.
    '#military_conflict' → '#MilitaryConflict'
    '#OSINT'             → '#OSINT'  (preserved)
    """
    raw = tag.lstrip("#").strip()
    lower = raw.lower()

    # Check curated replacements first
    if lower in _REPLACEMENTS:
        return "#" + _REPLACEMENTS[lower]

    # If already single word — preserve original casing (e.g. OSINT, Ukraine)
    if re.match(r"^[A-Za-z0-9]+$", raw):
        return "#" + raw

    # Multi-word or underscored — convert to CamelCase
    return "#" + _to_camel(raw)


def build(platform: str, raw_tags: list[str], level: str = "GREEN") -> str:
    """
    Return a space-separated hashtag string for the given platform.

    platform : 'telegram' | 'bluesky' | 'mastodon'
    raw_tags : tags from LLM (may be messy multi-word)
    level    : alert level — RED adds #Breaking on telegram/bluesky
    """
    base   = list(_BASE.get(platform, ["#OSINT"]))
    limit  = _LIMITS.get(platform, 4)

    if level == "RED" and platform in ("telegram", "bluesky"):
        base.insert(0, "#Breaking")

    # Normalize dynamic tags from LLM
    dynamic = [normalize(t) for t in raw_tags if t.strip()]

    # Merge: base first, then dynamic — deduplicated, case-insensitive
    seen: set[str] = set()
    result: list[str] = []
    for tag in base + dynamic:
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            result.append(tag)
        if len(result) >= limit:
            break

    return " ".join(result)
