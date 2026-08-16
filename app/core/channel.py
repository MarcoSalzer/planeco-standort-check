"""derive_channel: Kanal-Ableitung beim Speichern (Konzept §H).

Prioritätsreihenfolge, erste zutreffende Regel gewinnt:
utm_source -> gclid -> fbclid -> referrer (Google/Bing/DuckDuckGo) ->
heard_about (Selbstauskunft) -> direkt.

utm_source wird zweistufig gemappt (mit Marco abgestimmt, 2026-08-15):
erst exakter Abgleich gegen bekannte Plattform-Werte (channel_source='utm'),
erst wenn das nicht greift ein Substring-Fallback mit derselben Zuordnung,
aber channel_source='utm_unsicher'. Reines Substring-Matching auf "google"
würde sonst auch bei "googlemail" oder einem Kampagnennamen wie
"google-partner-blog" zuschlagen — falsch, aber unauffällig falsch.
"""

# Exakter Wortlaut der Select-Optionen im Formular (Konzept §3.2) — einzige
# Quelle für Formular-Rendering UND Kanal-Zuordnung, damit beide nie
# auseinanderlaufen.
HEARD_ABOUT_OPTIONS = (
    "Google-Suche",
    "Google-Anzeige",
    "Facebook oder Instagram",
    "Empfehlung",
    "Sonstiges",
)

_HEARD_ABOUT_CHANNEL = {
    "google-suche": "google_organisch",
    "google-anzeige": "google_ads",
    "facebook oder instagram": "meta_ads",
    "empfehlung": "empfehlung",
    "sonstiges": "sonstiges",
}

_UTM_SOURCE_EXACT = {
    "google": "google_ads",
    "facebook": "meta_ads",
    "meta": "meta_ads",
    "instagram": "meta_ads",
}

_UTM_SOURCE_SUBSTRINGS = (
    ("google", "google_ads"),
    ("facebook", "meta_ads"),
    ("meta", "meta_ads"),
    ("instagram", "meta_ads"),
)

# Anzeigetexte für die channel-Werte oben - fürs Dashboard (Konzept §6:
# Kanal-Spalte), damit dort kein snake_case-Code auftaucht.
CHANNEL_LABELS: dict[str, str] = {
    "google_ads": "Google Ads",
    "meta_ads": "Meta Ads",
    "google_organisch": "Google (organisch)",
    "andere_suche": "Andere Suchmaschine",
    "empfehlung": "Empfehlung",
    "direkt": "Direkt",
    "sonstiges": "Sonstiges",
}


def derive_channel(
    *,
    utm_source: str | None,
    gclid: str | None,
    fbclid: str | None,
    referrer: str | None,
    heard_about: str | None,
) -> tuple[str, str]:
    if utm_source:
        return _channel_from_utm_source(utm_source)
    if gclid:
        return "google_ads", "gclid"
    if fbclid:
        return "meta_ads", "fbclid"
    referrer_channel = _channel_from_referrer(referrer)
    if referrer_channel:
        return referrer_channel, "referrer"
    if heard_about:
        return _channel_from_heard_about(heard_about), "selbstauskunft"
    return "direkt", "keine"


def _channel_from_utm_source(utm_source: str) -> tuple[str, str]:
    value = utm_source.strip().lower()
    exact = _UTM_SOURCE_EXACT.get(value)
    if exact:
        return exact, "utm"
    for substring, channel in _UTM_SOURCE_SUBSTRINGS:
        if substring in value:
            return channel, "utm_unsicher"
    return "sonstiges", "utm"


def _channel_from_referrer(referrer: str | None) -> str | None:
    if not referrer:
        return None
    value = referrer.lower()
    if "google" in value:
        return "google_organisch"
    if "bing" in value or "duckduckgo" in value:
        return "andere_suche"
    return None


def _channel_from_heard_about(heard_about: str) -> str:
    return _HEARD_ABOUT_CHANNEL.get(heard_about.strip().lower(), "sonstiges")
