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

# Fallback für die Stadtstaaten (Fund beim Live-Test gegen die echte API,
# ausschließlich dort sichtbar - kein Fixture-Unit-Test hätte das gezeigt,
# s. docs/FUNDE.md): Nominatims address-Objekt hatte in Stichproben für
# Berlin und Hamburg KEIN "state"-Feld, nur den ISO-3166-2-Code - für
# Bremen dagegen doch (keine feste Regel je Bundesland, sondern Nominatims/
# OSMs uneinheitliche Datenpflege selbst innerhalb eines Bundeslands). Ohne
# diesen Fallback wäre geo_state in den lückenhaften Fällen still None,
# selbst bei einem eindeutigen Treffer. Codes sind offiziell und stabil
# (ISO 3166-2:DE) - eine Lookup-Tabelle für feste, dokumentierte Werte ist
# kein Raten im Sinne von CLAUDE.md Regel 12.
_ISO_3166_2_CODES = (
    "DE-BW", "DE-BY", "DE-BE", "DE-BB", "DE-HB", "DE-HH",
    "DE-HE", "DE-MV", "DE-NI", "DE-NW", "DE-RP", "DE-SL",
    "DE-SN", "DE-ST", "DE-SH", "DE-TH",
)
ISO_3166_2_TO_STATE: dict[str, str] = dict(zip(_ISO_3166_2_CODES, GERMAN_STATES))

# Nominatims addressdetails benennt die Gemeinde je nach Siedlungsgröße
# unterschiedlich (Großstadt -> city, Kleinstadt -> town, Dorf -> village,
# ...) - keine geratene Umwandlung (CLAUDE.md Regel 12), sondern Nominatims
# eigene, dokumentierte Uneinheitlichkeit über eine Prioritätsliste
# abgefangen: die erste vorhandene gewinnt.
_GEMEINDE_SCHLUESSEL = ("city", "town", "municipality", "village", "township", "hamlet")

_ALLE_SENTINEL = "alle"  # dieselbe Konvention wie die Tab-/Status-Filter in app/admin.py ("alle" = kein Filter)


def parse_service_area_states(raw: str) -> set[str]:
    """Parst SERVICE_AREA_STATES (Env-Variable, app/geocoding.py liest sie
    beim Modul-Import einmalig und bricht bei einem ungültigen Wert sofort
    ab statt still auf eine leere Menge zurückzufallen).

    Fund beim Live-Test (Marco, 2026-08-17, s. docs/FUNDE.md): ein leerer
    Wert bedeutete schon immer "alle 16 Bundesländer", das Wort "alle"
    selbst wurde aber nirgends erkannt und stattdessen als wörtlicher
    Bundesland-Name behandelt - SERVICE_AREA_STATES=alle ergab die
    Ein-Element-Menge {"alle"}, auf die kein echtes Bundesland je passt.
    Ergebnis: in_service_area wäre für JEDE Adresse still False gewesen,
    ohne jede Fehlermeldung. Derselbe Webfehler droht bei jedem Tippfehler
    (z.B. "Bayen" statt "Bayern") - deshalb hier zusätzlich eine echte
    Prüfung gegen GERMAN_STATES statt nur der Sentinel-Erkennung: ein
    unbekannter Eintrag wirft, statt einen Filter zu bilden, der nie
    zutrifft (CLAUDE.md Regel 12: nicht raten, nicht still falsch werden)."""
    value = raw.strip()
    if not value or value.lower() == _ALLE_SENTINEL:
        return set(GERMAN_STATES)
    eintraege = [s.strip() for s in value.split(",") if s.strip()]
    unbekannt = [s for s in eintraege if s not in GERMAN_STATES]
    if unbekannt:
        raise ValueError(
            f"Unbekannte Bundesland-Namen: {', '.join(unbekannt)!r}. Gültig sind "
            f"{_ALLE_SENTINEL!r}, ein leerer Wert, oder eine kommagetrennte Liste aus: "
            f"{', '.join(GERMAN_STATES)}."
        )
    return set(eintraege)


@dataclass(frozen=True)
class GeocodeResult:
    status: str  # ok | mehrdeutig | nicht_gefunden (fehlgeschlagen kommt aus app/geocoding.py, nicht von hier;
    # 'nur_ort' entsteht ebenfalls erst in app/geocoding.py::geocode() - eine Umbenennung eines hier
    # gelieferten 'ok'-Ergebnisses für den PLZ+Ort-Rückfall, kein eigener Rückgabewert dieser Funktion)
    raw: dict | None  # {"results": [...], "auswahl": {...}}, für geocode_raw - vollständige Antwort + Nachvollziehbarkeit der Entscheidung
    candidate_count: int  # bei mehrdeutig: Anzahl WIRKLICH verschiedener Orte (nicht roher Trefferzahl); bei ok immer 1
    lat: float | None
    lon: float | None
    geo_state: str | None
    geo_municipality: str | None
    geo_country: str | None  # ISO-Code (country_code), s. Schema-Kommentar
    in_service_area: bool | None  # None = unbekannt (kein state ermittelbar), nicht False
    geo_state_unresolved: bool  # True: eindeutiger/übereinstimmender Treffer, aber Bundesland trotz ISO-Fallback nicht ermittelbar - erkennbar statt still None (Marco, 2026-08-16)


def _extract_geo_state(address: dict) -> str | None:
    state = address.get("state")
    if state:
        return state
    iso_code = address.get("ISO3166-2-lvl4")
    if iso_code:
        return ISO_3166_2_TO_STATE.get(iso_code)  # None, falls kein deutscher Code (Ausland)
    return None


def _extract_geo_municipality(address: dict) -> str | None:
    return next((address[key] for key in _GEMEINDE_SCHLUESSEL if address.get(key)), None)


def _extract_geo_country(address: dict) -> str | None:
    code = address.get("country_code")
    return code.upper() if code else None


def candidate_summaries(results: list[dict]) -> list[dict]:
    """Bundesland/Gemeinde je Kandidat aus den rohen Nominatim-Ergebnissen
    - für die Detailansicht bei mehrdeutigen Treffern (Phase 4 Block d,
    Marco 2026-08-17: "damit Sales im Gespräch gezielt fragen kann").
    Nutzt dieselbe Extraktion wie parse_nominatim_results(), aber für ALLE
    Kandidaten statt nur den Gewinner - deshalb als eigene, öffentliche
    Funktion statt die private Gewinner-Logik zu verzweigen."""
    return [
        {
            "display_name": r.get("display_name"),
            "geo_state": _extract_geo_state(r.get("address", {})),
            "geo_municipality": _extract_geo_municipality(r.get("address", {})),
            "importance": r.get("importance"),
        }
        for r in results
    ]


@dataclass(frozen=True)
class _Kandidat:
    ergebnis: dict
    geo_state: str | None
    geo_municipality: str | None
    geo_country: str | None
    importance: float


def parse_nominatim_results(
    results: list[dict], *, service_area_states: set[str] | None = None
) -> GeocodeResult:
    """results: bereits dekodierte JSON-Liste von Nominatims /search
    (format=jsonv2, addressdetails=1). service_area_states: Bundesländer,
    die als Einzugsgebiet gelten - Default alle 16 (SERVICE_AREA_STATES-Env,
    s. app/geocoding.py).

    Mehrdeutig heißt NICHT "mehr als ein Treffer", sondern "Treffer, die
    sich fachlich widersprechen" (Marco, 2026-08-16, nach Live-Test gegen
    die echte API): eine vollständige Adresse liefert bei Nominatim oft
    mehrere OSM-Objekte an derselben Stelle (Gebäude, Ausstattung,
    Geschäfte) - dieselbe Gemeinde, dasselbe Bundesland. Kriterium ist
    deshalb, ob sich Bundesland ODER Gemeinde zwischen den Kandidaten
    unterscheiden. Stimmen alle überein, gewinnt der Kandidat mit dem
    höchsten Nominatim-`importance`-Wert als "genauester Treffer". Der
    Testfall "Lindenweg 3, Neustadt" (Aufgabe) bleibt mehrdeutig, weil dort
    tatsächlich drei verschiedene Bundesländer auftreten (Baden-Württemberg/
    Schleswig-Holstein/Sachsen - "Neustadt" als Ortsnamen-Fragment gibt es
    mehrfach).

    Jede Entscheidung wird in `raw.auswahl` protokolliert (wie viele
    Kandidaten es gab, ob sie übereinstimmten oder widersprachen, welcher
    gewählt wurde) - sonst wäre später nicht mehr nachvollziehbar, ob ein
    Treffer wirklich eindeutig war oder unter mehreren ausgewählt wurde.
    """
    service_area = service_area_states if service_area_states is not None else set(GERMAN_STATES)

    if not results:
        return GeocodeResult(
            status="nicht_gefunden",
            raw={"results": results, "auswahl": {"kandidaten_gesamt": 0, "eingestuft_als": "keine_treffer", "gewaehlter_index": None}},
            candidate_count=0,
            lat=None, lon=None, geo_state=None, geo_municipality=None,
            geo_country=None, in_service_area=None, geo_state_unresolved=False,
        )

    kandidaten = [
        _Kandidat(
            ergebnis=r,
            geo_state=_extract_geo_state(r.get("address", {})),
            geo_municipality=_extract_geo_municipality(r.get("address", {})),
            geo_country=_extract_geo_country(r.get("address", {})),
            importance=r.get("importance") or 0.0,
        )
        for r in results
    ]
    orte = {(k.geo_state, k.geo_municipality) for k in kandidaten}

    if len(orte) > 1:
        return GeocodeResult(
            status="mehrdeutig",
            raw={
                "results": results,
                "auswahl": {
                    "kandidaten_gesamt": len(results),
                    "eingestuft_als": "widerspruechlich",
                    "gewaehlter_index": None,
                },
            },
            # Anzahl WIRKLICH verschiedener Orte, nicht roher Trefferzahl -
            # 5 OSM-Treffer, die auf 2 echte Orte fallen, sind "2 mögliche
            # Orte" für die Ampel, nicht "5" (dieselbe Grundidee wie das
            # Übereinstimmungs-Kriterium selbst).
            candidate_count=len(orte),
            lat=None, lon=None, geo_state=None, geo_municipality=None,
            geo_country=None, in_service_area=None, geo_state_unresolved=False,
        )

    # Alle Kandidaten sind (Bundesland, Gemeinde)-gleich - ein eindeutiger
    # Ort, bei mehreren OSM-Objekten gewinnt der mit dem höchsten
    # importance-Wert (Nominatims eigene Relevanz-Kennzahl).
    gewinner_index = max(range(len(kandidaten)), key=lambda i: kandidaten[i].importance)
    gewinner = kandidaten[gewinner_index]
    ergebnis = gewinner.ergebnis

    lat = float(ergebnis["lat"]) if ergebnis.get("lat") is not None else None
    lon = float(ergebnis["lon"]) if ergebnis.get("lon") is not None else None
    in_service_area = (gewinner.geo_state in service_area) if gewinner.geo_state else None
    geo_state_unresolved = gewinner.geo_state is None

    return GeocodeResult(
        status="ok",
        raw={
            "results": results,
            "auswahl": {
                "kandidaten_gesamt": len(results),
                "eingestuft_als": "eindeutig" if len(results) == 1 else "uebereinstimmend",
                "gewaehlter_index": gewinner_index,
            },
        },
        candidate_count=1,
        lat=lat, lon=lon, geo_state=gewinner.geo_state, geo_municipality=gewinner.geo_municipality,
        geo_country=gewinner.geo_country, in_service_area=in_service_area,
        geo_state_unresolved=geo_state_unresolved,
    )
