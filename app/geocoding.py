"""Nominatim-Client (Konzept §1/§B/§G, Erweiterung C). Best effort: jeder
Fehlerfall liefert status='fehlgeschlagen' statt zu werfen (CLAUDE.md
Regel 2/3) - der Aufrufer (Retry-Endpunkt, POST /admin/retry) speichert
das Ergebnis und entscheidet über den nächsten Versuch.

DRY_RUN_GEOCODE wird hier bewusst NICHT geprüft: das ist wie
MAX_GEOCODE_PER_MINUTE eine Frage des Retry-Laufs (soll überhaupt
angefragt werden?), nicht des Clients selbst - dieses Modul ruft immer
wirklich Nominatim auf, wenn es aufgerufen wird.
"""
import logging
import os

import httpx

from app.core.geocoding import GeocodeResult, parse_nominatim_results, parse_service_area_states

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_TIMEOUT_SECONDS = 3.0

# Wird beim Modul-Import ausgewertet (wie app/config.py: MAX_EMAILS_PER_DAY
# etc.), nicht erst beim ersten Aufruf von geocode() - ein ungültiger Wert
# (Tippfehler im Bundesland-Namen, z.B. "Bayen") soll den Prozessstart mit
# einer klaren Meldung abbrechen statt unbemerkt einen Filter zu bilden, der
# nie zutrifft (Fund beim Live-Test, Marco 2026-08-17, s. docs/FUNDE.md).
try:
    SERVICE_AREA_STATES: set[str] = parse_service_area_states(os.environ.get("SERVICE_AREA_STATES", ""))
except ValueError as exc:
    raise RuntimeError(f"SERVICE_AREA_STATES (Env-Variable) ist ungültig: {exc}") from exc


def _fehlgeschlagen(fehler: str) -> GeocodeResult:
    return GeocodeResult(
        status="fehlgeschlagen", raw={"fehler": fehler}, candidate_count=0,
        lat=None, lon=None, geo_state=None, geo_municipality=None,
        geo_country=None, in_service_area=None, geo_state_unresolved=False,
    )


def geocode(*, street: str, postal_code: str | None, city: str) -> GeocodeResult:
    """Strukturierte Abfrage (Konzept: eigene Parameter statt Freitext-q=,
    damit Straße/PLZ/Ort einzeln ankommen). countrycodes=de statt
    country=Deutschland - genau ein Einschränkungsmechanismus, nicht zwei
    potenziell widersprüchliche."""
    user_agent = os.environ.get("NOMINATIM_USER_AGENT")
    if not user_agent:
        # Nominatims Nutzungsbedingungen verlangen einen identifizierenden
        # User-Agent - ohne den lieber gar nicht erst anfragen (Gefahr
        # einer IP-Sperre für alle, nicht nur uns) als einen Default zu
        # erfinden, der niemanden wirklich identifiziert.
        logger.warning("NOMINATIM_USER_AGENT nicht gesetzt - Geocoding-Anfrage übersprungen")
        return _fehlgeschlagen("NOMINATIM_USER_AGENT nicht konfiguriert")

    params: dict[str, str | int] = {
        "street": street,
        "city": city,
        "countrycodes": "de",
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 5,
    }
    if postal_code:
        params["postalcode"] = postal_code

    try:
        response = httpx.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": user_agent},
            timeout=NOMINATIM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        results = response.json()
    except Exception as exc:
        logger.warning("Nominatim-Anfrage fehlgeschlagen für %r/%r/%r: %s", street, postal_code, city, exc)
        return _fehlgeschlagen(str(exc))

    return parse_nominatim_results(results, service_area_states=SERVICE_AREA_STATES)
