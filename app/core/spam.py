"""detect_spam: die vier Verdachtsmuster aus Konzept §J.

Reine Funktion. Setzt nie eine harte Ablehnung, nur is_spam+spam_reason -
"es wird nie abgewiesen und nie gelöscht" (§J). Erste zutreffende Regel
gewinnt: Honeypot > Zeitschwelle > Link-Zähler > Zeichensatz.
"""
import re

_URL_RE = re.compile(r"https?://")
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_CJK_RE = re.compile(r"[一-鿿]")

MIN_SECONDS_BEFORE_SUBMIT = 3
MIN_URLS_FOR_SUSPICION = 2


def detect_spam(
    *,
    honeypot_value: str | None,
    elapsed_seconds: float | None,
    message: str | None,
) -> tuple[bool, str | None]:
    if honeypot_value and honeypot_value.strip():
        return True, "honeypot_gefuellt"

    if elapsed_seconds is not None and elapsed_seconds < MIN_SECONDS_BEFORE_SUBMIT:
        return True, "zu_schnell_abgesendet"

    if message:
        if len(_URL_RE.findall(message)) >= MIN_URLS_FOR_SUSPICION:
            return True, "zu_viele_links_in_anmerkung"
        if _CYRILLIC_RE.search(message) or _CJK_RE.search(message):
            return True, "fremdes_schriftsystem_in_anmerkung"

    return False, None
