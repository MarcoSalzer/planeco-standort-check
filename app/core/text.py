"""Gemeinsame Text-Kanonisierung für content_hash und Dedup-Matching.

Trim + Whitespace kollabieren + kleinschreiben. Bewusst simpel: keine
Umlaut-Transliteration, kein Unicode-Normalize über NFKC hinaus Bedarf -
nur das, was Formatvarianten (Leerzeichen, Groß-/Kleinschreibung) auf
denselben Wert bringt (R16).
"""


def canonical_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).lower()
