"""Reine Auswertung einer Nominatim-Antwort (Konzept §B/§G/Erweiterung C).

Kein HTTP-Zugriff hier - der eigentliche Client (app/geocoding.py) ruft
Nominatim auf und übergibt nur die schon geparste JSON-Liste. So bleibt
die Status-/Ableitungslogik ohne Netzwerk-Mock testbar (CLAUDE.md Regel 5).
"""
from dataclasses import dataclass

# Konzept §0: Einzugsgebiet ist bundesweit, SERVICE_AREA_STATES bleibt per
# Env-Variable überschreibbar (Pilot-Rollout auf einzelne Länder). Auch
# der Default für den Bundesland-Filter im Dashboard (app/admin.py).
GERMAN_STATES = (
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg",
    "Hessen", "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen",
    "Rheinland-Pfalz", "Saarland", "Sachsen", "Sachsen-Anhalt",
    "Schleswig-Holstein", "Thüringen",
)

# Nominatims addressdetails benennt die Gemeinde je nach Siedlungsgröße
# unterschiedlich (Großstadt -> city, Kleinstadt -> town, Dorf -> village,
# ...) - keine geratene Umwandlung (CLAUDE.md Regel 12), sondern Nominatims
# eigene, dokumentierte Uneinheitlichkeit über eine Prioritätsliste
# abgefangen: die erste vorhandene gewinnt.
_GEMEINDE_SCHLUESSEL = ("city", "town", "municipality", "village", "township", "hamlet")


@dataclass(frozen=True)
class GeocodeResult:
    status: str  # ok | mehrdeutig | nicht_gefunden (fehlgeschlagen kommt aus app/geocoding.py, nicht von hier)
    raw: list | dict | None  # vollständige Nominatim-Antwort, für geocode_raw
    candidate_count: int
    lat: float | None
    lon: float | None
    geo_state: str | None
    geo_municipality: str | None
    geo_country: str | None  # ISO-Code (country_code), s. Schema-Kommentar
    in_service_area: bool | None  # None = unbekannt (kein state ermittelbar), nicht False


def parse_nominatim_results(
    results: list[dict], *, service_area_states: set[str] | None = None
) -> GeocodeResult:
    """results: bereits dekodierte JSON-Liste von Nominatims /search
    (format=jsonv2, addressdetails=1). service_area_states: Bundesländer,
    die als Einzugsgebiet gelten - Default alle 16 (SERVICE_AREA_STATES-Env,
    s. app/geocoding.py)."""
    service_area = service_area_states if service_area_states is not None else set(GERMAN_STATES)

    if not results:
        return GeocodeResult(
            status="nicht_gefunden", raw=results, candidate_count=0,
            lat=None, lon=None, geo_state=None, geo_municipality=None,
            geo_country=None, in_service_area=None,
        )

    if len(results) > 1:
        return GeocodeResult(
            status="mehrdeutig", raw=results, candidate_count=len(results),
            lat=None, lon=None, geo_state=None, geo_municipality=None,
            geo_country=None, in_service_area=None,
        )

    result = results[0]
    address = result.get("address", {})
    geo_state = address.get("state")
    geo_municipality = next(
        (address[key] for key in _GEMEINDE_SCHLUESSEL if address.get(key)), None
    )
    geo_country = address.get("country_code")
    geo_country = geo_country.upper() if geo_country else None
    lat = float(result["lat"]) if result.get("lat") is not None else None
    lon = float(result["lon"]) if result.get("lon") is not None else None
    # None statt False, wenn wir gar kein Bundesland ermitteln konnten -
    # "wissen wir nicht" ist etwas anderes als "wissen wir, liegt außerhalb"
    # (CLAUDE.md Regel 12, dieselbe Unterscheidung wie in app/core/ampel.py).
    in_service_area = (geo_state in service_area) if geo_state else None

    return GeocodeResult(
        status="ok", raw=results, candidate_count=1,
        lat=lat, lon=lon, geo_state=geo_state, geo_municipality=geo_municipality,
        geo_country=geo_country, in_service_area=in_service_area,
    )
