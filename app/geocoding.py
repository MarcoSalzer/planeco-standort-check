"""Nominatim-Client (Konzept §1/§B/§G, Erweiterung C). Best effort: jeder
Fehlerfall liefert status='fehlgeschlagen' statt zu werfen (CLAUDE.md
Regel 2/3) - der Aufrufer (Retry-Endpunkt, POST /admin/retry) speichert
das Ergebnis und entscheidet über den nächsten Versuch.

DRY_RUN_GEOCODE wird hier bewusst NICHT geprüft: das ist wie
MAX_GEOCODE_PER_MINUTE eine Frage des Retry-Laufs (soll überhaupt
angefragt werden?), nicht des Clients selbst - dieses Modul ruft immer
wirklich Nominatim auf, wenn es aufgerufen wird.
"""
import dataclasses
import logging
import os
import time

import httpx

from app.core.geocoding import GeocodeResult, parse_nominatim_results, parse_service_area_states

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_TIMEOUT_SECONDS = 3.0
# Nominatim-Nutzungsbedingungen: max. 1 Anfrage/Sekunde. Hier definiert
# (nicht nur in app/retry.py, das früher die einzige Stelle mit Pausen
# zwischen Anfragen war), weil geocode() jetzt selbst bis zu zwei Anfragen
# hintereinander stellen kann (Straßen-Versuch + Ortsebene-Rückfall,
# 2026-08-18) - der Abstand gilt für JEDE Anfrage an Nominatim, nicht nur
# zwischen verschiedenen Leads im Batch. app/retry.py importiert diese
# Konstante jetzt von hier, statt sie ein zweites Mal zu pflegen.
NOMINATIM_MIN_INTERVAL_SECONDS = 1.1

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


def _nominatim_get(params: dict[str, str | int], user_agent: str) -> list[dict]:
    response = httpx.get(
        NOMINATIM_URL,
        params=params,
        headers={"User-Agent": user_agent},
        timeout=NOMINATIM_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def geocode(*, street: str, postal_code: str | None, city: str) -> GeocodeResult:
    """Strukturierte Abfrage (Konzept: eigene Parameter statt Freitext-q=,
    damit Straße/PLZ/Ort einzeln ankommen). countrycodes=de statt
    country=Deutschland - genau ein Einschränkungsmechanismus, nicht zwei
    potenziell widersprüchliche.

    Rückfall auf Ortsebene (Marco, 2026-08-18, nach dem OSM-Fund in
    docs/FUNDE.md: die Straße "Am Mühlenteich" in Groß Grönau ist in
    OpenStreetMap nicht erfasst, PLZ+Ort allein aber sauber auflösbar):
    liefert die Abfrage MIT Straße null Treffer, wird automatisch ein
    zweiter, strukturierter Versuch NUR mit PLZ+Ort gestellt. Gelingt der,
    steht das Ergebnis als geocode_status='nur_ort' - Bundesland/Gemeinde/
    Koordinaten auf Ortsebene, aber erkennbar unvollständig gegenüber einem
    echten Straßentreffer ('ok')."""
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
        results = _nominatim_get(params, user_agent)
    except Exception as exc:
        logger.warning("Nominatim-Anfrage fehlgeschlagen für %r/%r/%r: %s", street, postal_code, city, exc)
        return _fehlgeschlagen(str(exc))

    result = parse_nominatim_results(results, service_area_states=SERVICE_AREA_STATES)

    if result.status == "nicht_gefunden":
        # 1.1s Pause: dieselbe Ratenbegrenzung wie zwischen zwei Leads im
        # Batch (s. NOMINATIM_MIN_INTERVAL_SECONDS oben) - gilt für jede
        # einzelne Anfrage an Nominatim, auch innerhalb dieses einen
        # geocode()-Aufrufs.
        time.sleep(NOMINATIM_MIN_INTERVAL_SECONDS)
        ort_params: dict[str, str | int] = {
            "city": city,
            "countrycodes": "de",
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 5,
        }
        if postal_code:
            ort_params["postalcode"] = postal_code

        try:
            ort_results = _nominatim_get(ort_params, user_agent)
        except Exception as exc:
            # Der Rückfall selbst ist best effort - schlägt ER fehl, bleibt
            # das ORIGINALE 'nicht_gefunden'-Ergebnis stehen statt den
            # ganzen Versuch als 'fehlgeschlagen' zu werten (der erste,
            # maßgebliche Versuch WAR erfolgreich beantwortet, nur ohne
            # Treffer).
            logger.warning("Ortsebene-Rückfall fehlgeschlagen für %r/%r: %s", postal_code, city, exc)
        else:
            ort_ergebnis = parse_nominatim_results(ort_results, service_area_states=SERVICE_AREA_STATES)
            if ort_ergebnis.status == "ok":
                # Nicht als 'ok' übernehmen: das Ergebnis bestätigt nur den
                # ORT, nicht die vollständige Adresse. 'mehrdeutig'/
                # 'nicht_gefunden' auf Ortsebene lassen das ursprüngliche
                # 'nicht_gefunden' unverändert stehen - ein unsicherer
                # Rückfall ist kein Rückfall.
                result = dataclasses.replace(
                    ort_ergebnis,
                    status="nur_ort",
                    raw={"strasse_versuch": result.raw, "ort_ergebnis": ort_ergebnis.raw},
                )

    return result
