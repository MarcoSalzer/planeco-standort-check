"""Reine Normalisierungsfunktionen ohne DB- oder HTTP-Zugriff.

Konservativ (CLAUDE.md Regel 12): wo eine Umwandlung raten müsste, wird
nicht umgewandelt. Der Rohwert bleibt beim Aufrufer erhalten, diese
Funktionen liefern nur den (ggf. unveränderten) normalisierten Wert.
"""
import re

from app.core.channel import HEARD_ABOUT_OPTIONS

_PHONE_SEPARATORS = re.compile(r"[\s()/.-]+")
_PHONE_SHAPE = re.compile(r"\+\d{8,15}")

_NAME_PARTICLES = {
    "von", "van", "de", "del", "di", "da", "der",
    "den", "zu", "zum", "la", "le", "ter",
}


def normalize_phone(raw: str | None) -> tuple[str | None, bool]:
    """Wandelt eine deutsche Telefonnummer nach E.164 um.

    Erkennt +-Präfix, 00-Präfix und nationalen 0-Präfix. Alles andere
    (fehlende Landeskennung, zu kurz, nicht-numerisch) bleibt unangetastet
    statt geraten zu werden.
    """
    if not raw or not raw.strip():
        return None, False

    cleaned = _PHONE_SEPARATORS.sub("", raw.strip())

    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif cleaned.startswith("0"):
        cleaned = "+49" + cleaned[1:]
    elif not cleaned.startswith("+"):
        return None, False

    if not _PHONE_SHAPE.fullmatch(cleaned):
        return None, False

    return cleaned, True


def normalize_email(raw: str) -> str:
    """Trim + lowercase, wie in Konzept §1 Schritt 3 festgelegt."""
    return raw.strip().lower()


def normalize_name(raw: str | None) -> tuple[str | None, bool]:
    """Titelcase nur bei durchgängig GROSS oder klein geschriebenem Namen
    OHNE Namenspartikel.

    Gemischte Schreibweisen (McDonald, O'Brien, di Marco) bleiben
    unangetastet, weil dort echte Namensformen stecken (Konzept §I).
    Namen mit Partikel (von, van, de, ...) werden nie normalisiert: ob ein
    Partikel am Satzanfang groß oder klein gehört, hängt vom
    Herkunftskontext ab — das wäre Raten, und Raten ist nach CLAUDE.md
    Regel 12 ausgeschlossen (mit Marco abgestimmt, 2026-08-15).
    """
    if raw is None:
        return raw, False

    stripped = raw.strip()
    if not stripped:
        return raw, False

    words = stripped.split(" ")
    if any(word.lower() in _NAME_PARTICLES for word in words):
        return raw, False

    if not (stripped.isupper() or stripped.islower()):
        return raw, False

    normalized_words = [_capitalize_word(word) for word in words]
    return " ".join(normalized_words), True


def _capitalize_word(word: str) -> str:
    if not word:
        return word
    if "-" in word:
        return "-".join(_capitalize_segment(part) for part in word.split("-"))
    return _capitalize_segment(word)


def _capitalize_segment(segment: str) -> str:
    if "'" in segment:
        before, _, after = segment.partition("'")
        return f"{before.capitalize()}'{after.capitalize()}"
    return segment.capitalize()


def normalize_heard_about(raw: str | None) -> tuple[str | None, bool]:
    """Prüft gegen HEARD_ABOUT_OPTIONS (Konzept §3.2), analog zu
    contact_time_preference - aber anders als dort: kein 422. Ein Wert kann
    hier nur bei einem direkten POST unter der HTML-Auswahl vorbeikommen
    (die <select>-Optionen sind identisch mit HEARD_ABOUT_OPTIONS), das ist
    kein Nutzerfehler, der die ganze Anfrage verdient, sondern etwas, das
    im Statusfeld/Event festgehalten gehört (CLAUDE.md Regel 3) statt die
    Anfrage abzulehnen oder den Wert zu erraten (Regel 12). Der Aufrufer
    schreibt bei True ein Event 'unerwarteter_feldwert' und speichert None
    statt des unbekannten Rohwerts.
    """
    if not raw or not raw.strip():
        return None, False
    stripped = raw.strip()
    if stripped in HEARD_ABOUT_OPTIONS:
        return stripped, False
    return None, True
