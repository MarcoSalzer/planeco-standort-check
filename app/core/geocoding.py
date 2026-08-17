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
    status: str  # ok | mehrdeutig | nicht_gefunden | plz_abweichend (fehlgeschlagen kommt aus
    # app/geocoding.py, nicht von hier; 'nur_ort' entsteht ebenfalls erst in
    # app/geocoding.py::geocode() - eine Umbenennung eines hier gelieferten 'ok'- oder
    # 'plz_abweichend'-Ergebnisses für den PLZ+Ort-Rückfall, kein eigener Rückgabewert dieser Funktion)
    raw: dict | None  # {"results": [...], "auswahl": {...}}, für geocode_raw - vollständige Antwort + Nachvollziehbarkeit der Entscheidung
    candidate_count: int  # bei mehrdeutig: Anzahl WIRKLICH verschiedener Orte (nicht roher Trefferzahl); bei ok/plz_abweichend immer 1
    lat: float | None
    lon: float | None
    geo_state: str | None
    geo_municipality: str | None
    geo_country: str | None  # ISO-Code (country_code), s. Schema-Kommentar
    geo_postal_code: str | None  # die von Nominatim GEFUNDENE PLZ (nicht die Eingabe) - nur bei
    # status='plz_abweichend' inhaltlich von der Eingabe verschieden, s. dort
    in_service_area: bool | None  # None = unbekannt (weder country_code != DE noch state ermittelbar), nicht False
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


def _normalisiert_wie_dedup(value: str) -> str:
    """Gleiche Normalisierung wie der Duplikat-Vergleich (city_norm in
    app/submission.py::_find_dedup_candidate: lower(trim(city))) - dieselbe
    Regel gilt jetzt auch beim Abgleich Eingabe vs. Nominatim-Ergebnis
    (Marco, 2026-08-18), damit beide Stellen konsistent bleiben statt zwei
    unabhängige Normalisierungen zu pflegen."""
    return value.strip().lower()


def _ort_stimmt_ueberein(address: dict, erwarteter_ort: str) -> bool:
    erwartet_norm = _normalisiert_wie_dedup(erwarteter_ort)
    return any(
        _normalisiert_wie_dedup(address[schluessel]) == erwartet_norm
        for schluessel in _GEMEINDE_SCHLUESSEL
        if address.get(schluessel)
    )


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
    results: list[dict],
    *,
    expected_postal_code: str | None,
    expected_city: str,
    service_area_states: set[str] | None = None,
) -> GeocodeResult:
    """results: bereits dekodierte JSON-Liste von Nominatims /search
    (format=jsonv2, addressdetails=1). expected_postal_code/expected_city:
    die vom Nutzer eingegebenen Werte, gegen die JEDER Kandidat geprüft wird
    (s. u.). service_area_states: Bundesländer, die als Einzugsgebiet
    gelten - Default alle 16 (SERVICE_AREA_STATES-Env, s. app/geocoding.py).

    Abgleich Eingabe vs. Ergebnis (Marco, 2026-08-18, nach dem Fund in
    docs/FUNDE.md: seit app/geocoding.py::geocode() nicht mehr auf
    countrycodes=de beschränkt sucht, lieferte Nominatim für "Stephansplatz
    1, 1010 Wien" unscharf einen Weiler namens "Wien" in Bayern, PLZ 83334 -
    eine vierstellige österreichische PLZ, die in Deutschland gar nicht
    existiert, wurde nie gegen das Ergebnis geprüft). Zwei getrennte
    Kriterien, bewusst unterschiedlich streng:

    - **Ortsname (hart):** muss - nach derselben Normalisierung wie der
      Duplikat-Vergleich (lower/trim) - mit mindestens einem der Nominatim-
      Ortsfelder (city/town/municipality/village/township/hamlet)
      übereinstimmen. Kein Kandidat erfüllt das -> nicht_gefunden,
      unabhängig davon, wie viele Treffer Nominatim insgesamt lieferte.
    - **PLZ (weich, erst am gewählten Kandidaten geprüft):** eine FEHLENDE
      PLZ in der Antwort ist KEIN Widerspruch (Verwaltungsgrenzen-Objekte
      wie Dörfer/Gemeinden liefern grundsätzlich keine PLZ, s.
      docs/FUNDE.md - das hätte sonst den Ortsebene-Rückfall aus Punkt 1
      derselben Session für genau seinen eigenen Zielfall unbrauchbar
      gemacht). Eine TATSÄCHLICH abweichende PLZ verwirft den Treffer
      NICHT, sondern markiert ihn als status='plz_abweichend' statt 'ok' -
      ein Interessent, der sich bei einem optionalen Feld vertippt, aber
      dessen Ort eindeutig stimmt, soll nicht auf Rot landen (Marco,
      2026-08-18). Der gemeinsame Fehler, den das behebt: "kein Wert" und
      "falscher Wert" gleich zu behandeln erzeugt falsche Negative - trat
      in dieser Session dreimal auf (PLZ hier, Bundesland in §4/AT-Codes,
      Telefon schon vorher in app/core/ampel.py).

    Gilt für JEDEN Aufruf gleichermaßen (den ersten Versuch MIT Straße und
    den Ortsebene-Rückfall in geocode()) - dieselbe Funktion, dieselbe
    Prüfung, kein Sonderfall für den Rückfall.

    Mehrdeutig heißt NICHT "mehr als ein Treffer", sondern "Treffer, die
    sich fachlich widersprechen" (Marco, 2026-08-16, nach Live-Test gegen
    die echte API): eine vollständige Adresse liefert bei Nominatim oft
    mehrere OSM-Objekte an derselben Stelle (Gebäude, Ausstattung,
    Geschäfte) - dieselbe Gemeinde, dasselbe Bundesland. Kriterium ist
    deshalb, ob sich Bundesland ODER Gemeinde zwischen den (bereits auf
    Ortsnamen-Übereinstimmung gefilterten) Kandidaten unterscheiden (PLZ
    spielt für die Mehrdeutig-Erkennung keine Rolle, nur für den
    letztendlich gewählten Kandidaten). Stimmen alle überein, gewinnt der
    Kandidat mit dem höchsten Nominatim-`importance`-Wert als "genauester
    Treffer". Der Testfall "Lindenweg 3, Neustadt" (Aufgabe) bleibt
    mehrdeutig, weil dort tatsächlich drei verschiedene Bundesländer
    auftreten (Baden-Württemberg/Schleswig-Holstein/Sachsen - "Neustadt"
    als Ortsnamen-Fragment gibt es mehrfach).

    Jede Entscheidung wird in `raw.auswahl` protokolliert (wie viele
    Kandidaten es gab, ob sie übereinstimmten oder widersprachen, welcher
    gewählt wurde) - sonst wäre später nicht mehr nachvollziehbar, ob ein
    Treffer wirklich eindeutig war oder unter mehreren ausgewählt wurde.
    `gewaehlter_index` bezieht sich auf die Position im UNGEFILTERTEN
    `results` (nicht auf die Position nach dem Ortsnamen-Abgleich), damit
    der Index in `geocode_raw` immer auf `raw["results"]` zeigt, egal ob
    und wie viel gefiltert wurde.
    """
    service_area = service_area_states if service_area_states is not None else set(GERMAN_STATES)

    passende = [
        (index, r) for index, r in enumerate(results)
        if _ort_stimmt_ueberein(r.get("address", {}), expected_city)
    ]

    if not passende:
        return GeocodeResult(
            status="nicht_gefunden",
            raw={
                "results": results,
                "auswahl": {
                    "kandidaten_gesamt": len(results),
                    "eingestuft_als": "keine_treffer" if not results else "kein_passender_treffer",
                    "gewaehlter_index": None,
                },
            },
            candidate_count=0,
            lat=None, lon=None, geo_state=None, geo_municipality=None,
            geo_country=None, geo_postal_code=None, in_service_area=None, geo_state_unresolved=False,
        )

    kandidaten = [
        _Kandidat(
            ergebnis=r,
            geo_state=_extract_geo_state(r.get("address", {})),
            geo_municipality=_extract_geo_municipality(r.get("address", {})),
            geo_country=_extract_geo_country(r.get("address", {})),
            importance=r.get("importance") or 0.0,
        )
        for _, r in passende
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
            geo_country=None, geo_postal_code=None, in_service_area=None, geo_state_unresolved=False,
        )

    # Alle (adress-geprüften) Kandidaten sind (Bundesland, Gemeinde)-gleich -
    # ein eindeutiger Ort, bei mehreren OSM-Objekten gewinnt der mit dem
    # höchsten importance-Wert (Nominatims eigene Relevanz-Kennzahl).
    gewinner_position = max(range(len(kandidaten)), key=lambda i: kandidaten[i].importance)
    gewinner = kandidaten[gewinner_position]
    gewinner_index = passende[gewinner_position][0]  # Position im ungefilterten results
    ergebnis = gewinner.ergebnis

    lat = float(ergebnis["lat"]) if ergebnis.get("lat") is not None else None
    lon = float(ergebnis["lon"]) if ergebnis.get("lon") is not None else None

    # Land vor Bundesland (Marco, 2026-08-18, s. docs/FUNDE.md): country_code
    # liefert Nominatim IMMER mit, unabhängig davon, ob ein state-Feld
    # existiert (Wien z.B. hat keins, nur "ISO3166-2-lvl4": "AT-9" - eine
    # deutschlandspezifische ISO-Tabelle hilft dort nicht). Ist das Land
    # nicht DE, ist die Adresse unabhängig vom Bundesland außerhalb des
    # Einzugsgebiets - keine Codetabelle pro Land nötig. Nur wenn das Land
    # DE ist (oder unbekannt), entscheidet weiterhin SERVICE_AREA_STATES.
    if gewinner.geo_country and gewinner.geo_country != "DE":
        in_service_area = False
    elif gewinner.geo_state:
        in_service_area = gewinner.geo_state in service_area
    else:
        in_service_area = None
    geo_state_unresolved = gewinner.geo_state is None

    # PLZ-Abweichung nur am GEWÄHLTEN Kandidaten geprüft (nicht als
    # Filterkriterium, s. Docstring oben): fehlt sie in der Antwort, ist
    # das kein Widerspruch; weicht sie tatsächlich ab, bleibt der Treffer
    # gültig, aber der Status macht die Abweichung sichtbar statt sie zu
    # verschweigen.
    gefundene_plz = ergebnis.get("address", {}).get("postcode") or None
    plz_weicht_ab = bool(expected_postal_code) and bool(gefundene_plz) and gefundene_plz != expected_postal_code

    return GeocodeResult(
        status="plz_abweichend" if plz_weicht_ab else "ok",
        raw={
            "results": results,
            "auswahl": {
                "kandidaten_gesamt": len(results),
                "eingestuft_als": "eindeutig" if len(passende) == 1 else "uebereinstimmend",
                "gewaehlter_index": gewinner_index,
            },
        },
        candidate_count=1,
        lat=lat, lon=lon, geo_state=gewinner.geo_state, geo_municipality=gewinner.geo_municipality,
        geo_country=gewinner.geo_country, geo_postal_code=gefundene_plz, in_service_area=in_service_area,
        geo_state_unresolved=geo_state_unresolved,
    )
