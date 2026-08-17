import pytest

from app.core.geocoding import (
    GERMAN_STATES,
    ISO_3166_2_TO_STATE,
    candidate_summaries,
    parse_nominatim_results,
    parse_service_area_states,
)


def _result(*, importance=0.5, address=None, lat="53.5510846", lon="9.9936818", **overrides) -> dict:
    base = {
        "place_id": 12345,
        "lat": lat,
        "lon": lon,
        "importance": importance,
        "display_name": "Musterstraße 12, Hamburg, Deutschland",
        "address": address if address is not None else {
            "road": "Musterstraße",
            "house_number": "12",
            "city": "Hamburg",
            "state": "Hamburg",
            "postcode": "20095",
            "country": "Deutschland",
            "country_code": "de",
        },
    }
    base.update(overrides)
    return base


# --- Grundfälle: leer / genau ein Treffer -----------------------------------


def test_leere_liste_ist_nicht_gefunden():
    result = parse_nominatim_results([])
    assert result.status == "nicht_gefunden"
    assert result.candidate_count == 0
    assert result.in_service_area is None
    assert result.geo_state_unresolved is False
    assert result.raw == {"results": [], "auswahl": {"kandidaten_gesamt": 0, "eingestuft_als": "keine_treffer", "gewaehlter_index": None}}


def test_ein_treffer_ist_ok_und_eindeutig():
    result = parse_nominatim_results([_result()])
    assert result.status == "ok"
    assert result.candidate_count == 1
    assert result.geo_state == "Hamburg"
    assert result.geo_municipality == "Hamburg"
    assert result.geo_country == "DE"
    assert result.in_service_area is True
    assert result.lat == pytest.approx(53.5510846)
    assert result.lon == pytest.approx(9.9936818)
    assert result.raw["auswahl"] == {"kandidaten_gesamt": 1, "eingestuft_als": "eindeutig", "gewaehlter_index": 0}


# --- Neues Kriterium: übereinstimmend vs. widersprüchlich -------------------
# (Fund beim Live-Test: eine vollständige Adresse liefert oft mehrere OSM-
# Objekte an DERSELBEN Stelle - Gebäude, Ausstattung, Geschäfte. "Mehrdeutig"
# darf das nicht mehr heißen, sonst steht das Dashboard fast durchgängig auf
# Gelb und die Ampel verliert ihren Zweck, Marco 2026-08-16.)


def test_mehrere_treffer_am_selben_ort_gelten_als_eindeutig_wie_reales_beispiel_reichstag():
    # Nachgebaut aus dem echten Live-Fund: "Reichstagsgebäude" (importance
    # hoch) und "Reichstagskuppel" (importance niedrig) an derselben Stelle.
    gebaeude = _result(
        importance=0.549, lat="52.5186538", lon="13.3761015",
        address={"tourism": "Reichstagsgebäude", "city": "Berlin", "ISO3166-2-lvl4": "DE-BE", "postcode": "11011", "country_code": "de"},
    )
    kuppel = _result(
        importance=0.205, lat="52.5185931", lon="13.3761064",
        address={"tourism": "Reichstagskuppel", "city": "Berlin", "ISO3166-2-lvl4": "DE-BE", "postcode": "10557", "country_code": "de"},
    )
    result = parse_nominatim_results([kuppel, gebaeude])  # absichtlich in "falscher" Reihenfolge
    assert result.status == "ok"
    assert result.candidate_count == 1
    assert result.geo_state == "Berlin"
    # Der wichtigere Treffer (Gebäude, nicht die Kuppel) gewinnt trotz Position 1.
    assert result.lat == pytest.approx(52.5186538)
    assert result.raw["auswahl"] == {"kandidaten_gesamt": 2, "eingestuft_als": "uebereinstimmend", "gewaehlter_index": 1}


def test_fuenf_treffer_am_selben_ort_gelten_als_eindeutig_wie_reales_beispiel_marienplatz():
    # Nachgebaut: Rathaus (importance hoch) plus vier Nebenfunde (Defibrillator
    # etc., importance nahe 0) am selben Gebäude "Marienplatz 8, München".
    rathaus = _result(importance=0.389, address={"city": "München", "state": "Bayern", "postcode": "80331", "country_code": "de"})
    nebenfunde = [
        _result(importance=0.0000846, address={"city": "München", "state": "Bayern", "postcode": "80331", "country_code": "de"})
        for _ in range(4)
    ]
    result = parse_nominatim_results(nebenfunde + [rathaus])
    assert result.status == "ok"
    assert result.raw["auswahl"]["gewaehlter_index"] == 4  # das Rathaus steht als letztes in der Liste


def test_widerspruechliche_treffer_bleiben_mehrdeutig_testfall_lindenweg_neustadt():
    # Der Testfall aus der Aufgabe: "Lindenweg 3, Neustadt" ohne PLZ trifft
    # auf drei verschiedene Bundesländer (Neustadt im Schwarzwald/in
    # Holstein/in Sachsen) - MUSS mehrdeutig bleiben.
    kandidaten = [
        _result(address={"city": "Neustadt im Schwarzwald", "state": "Baden-Württemberg", "postcode": "79822", "country_code": "de"}),
        _result(address={"city": "Neustadt in Holstein", "state": "Schleswig-Holstein", "postcode": "23730", "country_code": "de"}),
        _result(address={"city": "Neustadt in Sachsen", "state": "Sachsen", "postcode": "01844", "country_code": "de"}),
    ]
    result = parse_nominatim_results(kandidaten)
    assert result.status == "mehrdeutig"
    assert result.candidate_count == 3
    assert result.geo_state is None
    assert result.in_service_area is None
    assert result.raw["auswahl"] == {"kandidaten_gesamt": 3, "eingestuft_als": "widerspruechlich", "gewaehlter_index": None}


def test_mehrdeutig_zaehlt_echte_orte_nicht_rohe_trefferzahl():
    # 4 rohe Treffer, aber nur 2 wirklich verschiedene Orte -> candidate_count
    # soll 2 sein ("2 mögliche Orte"), nicht 4 - sonst genau dieselbe
    # Irreführung, die der Fix eigentlich beheben soll.
    ort_a = {"city": "Dorf A", "state": "Bayern", "country_code": "de"}
    ort_b = {"city": "Dorf B", "state": "Hessen", "country_code": "de"}
    kandidaten = [_result(address=ort_a), _result(address=ort_a), _result(address=ort_b), _result(address=ort_b)]
    result = parse_nominatim_results(kandidaten)
    assert result.status == "mehrdeutig"
    assert result.candidate_count == 2


def test_unterschiedliche_gemeinde_bei_gleichem_bundesland_ist_auch_mehrdeutig():
    kandidaten = [
        _result(address={"city": "Musterstadt", "state": "Bayern", "country_code": "de"}),
        _result(address={"city": "Andersstadt", "state": "Bayern", "country_code": "de"}),
    ]
    result = parse_nominatim_results(kandidaten)
    assert result.status == "mehrdeutig"


# --- candidate_summaries: Kandidatenliste für die Detailansicht (Block d) --


def test_candidate_summaries_je_kandidat_bundesland_und_gemeinde():
    kandidaten = [
        _result(
            display_name="Neustadt im Schwarzwald, Baden-Württemberg",
            importance=0.4,
            address={"city": "Neustadt im Schwarzwald", "state": "Baden-Württemberg", "postcode": "79822", "country_code": "de"},
        ),
        _result(
            display_name="Neustadt in Sachsen, Sachsen",
            importance=0.3,
            address={"city": "Neustadt in Sachsen", "state": "Sachsen", "postcode": "01844", "country_code": "de"},
        ),
    ]
    summaries = candidate_summaries(kandidaten)
    assert len(summaries) == 2
    assert summaries[0] == {
        "display_name": "Neustadt im Schwarzwald, Baden-Württemberg",
        "geo_state": "Baden-Württemberg", "geo_municipality": "Neustadt im Schwarzwald", "importance": 0.4,
    }
    assert summaries[1]["geo_state"] == "Sachsen"


def test_candidate_summaries_leere_liste():
    assert candidate_summaries([]) == []


def test_candidate_summaries_nutzt_denselben_iso_fallback_wie_der_gewinner():
    kandidaten = [_result(address={"city": "Berlin", "ISO3166-2-lvl4": "DE-BE", "country_code": "de"})]
    assert candidate_summaries(kandidaten)[0]["geo_state"] == "Berlin"


# --- Stadtstaaten-Fund: ISO3166-2-lvl4-Fallback -----------------------------


@pytest.mark.parametrize("code,erwartetes_bundesland", [("DE-BE", "Berlin"), ("DE-HH", "Hamburg"), ("DE-HB", "Bremen")])
def test_stadtstaaten_ohne_state_feld_werden_ueber_iso_code_aufgeloest(code, erwartetes_bundesland):
    # Fund beim Live-Test: Nominatims address-Objekt hat für Stadtstaaten
    # KEIN "state"-Feld, nur den ISO-3166-2-Code.
    address = {"city": erwartetes_bundesland, "ISO3166-2-lvl4": code, "country_code": "de"}
    result = parse_nominatim_results([_result(address=address)])
    assert result.geo_state == erwartetes_bundesland
    assert result.in_service_area is True
    assert result.geo_state_unresolved is False


def test_alle_16_iso_codes_sind_korrekt_zugeordnet():
    assert set(ISO_3166_2_TO_STATE.values()) == set(GERMAN_STATES)
    assert len(ISO_3166_2_TO_STATE) == 16


def test_state_feld_hat_vorrang_vor_iso_code_falls_beide_da_sind():
    address = {"city": "Irgendwo", "state": "Bayern", "ISO3166-2-lvl4": "DE-TH", "country_code": "de"}
    result = parse_nominatim_results([_result(address=address)])
    assert result.geo_state == "Bayern"


def test_auslaendischer_iso_code_wird_nicht_als_deutsches_bundesland_gewertet():
    address = {"city": "Wien", "ISO3166-2-lvl4": "AT-9", "country_code": "at"}
    result = parse_nominatim_results([_result(address=address)])
    assert result.geo_state is None
    assert result.geo_state_unresolved is True


# --- "erkennbar bleibt": geo_state_unresolved -------------------------------


def test_fehlendes_bundesland_bei_sonst_eindeutigem_treffer_ist_erkennbar_markiert():
    address = {"city": "Irgendwo", "country_code": "de"}  # weder state noch ISO3166-2-lvl4
    result = parse_nominatim_results([_result(address=address)])
    assert result.status == "ok"
    assert result.geo_state is None
    assert result.geo_state_unresolved is True
    assert result.in_service_area is None  # "wissen wir nicht", nicht "liegt draußen"


def test_aufgeloestes_bundesland_ist_nicht_als_unresolved_markiert():
    result = parse_nominatim_results([_result()])
    assert result.geo_state_unresolved is False


def test_nicht_gefunden_und_mehrdeutig_sind_nicht_unresolved_markiert():
    # geo_state_unresolved gilt nur für den "eindeutiger Treffer, aber kein
    # Bundesland ermittelbar"-Fall, nicht für die anderen beiden Status.
    assert parse_nominatim_results([]).geo_state_unresolved is False
    widerspruch = [
        _result(address={"state": "Bayern", "city": "A", "country_code": "de"}),
        _result(address={"state": "Hessen", "city": "B", "country_code": "de"}),
    ]
    assert parse_nominatim_results(widerspruch).geo_state_unresolved is False


# --- Gemeinde-Schlüssel-Fallback (unverändert von vorher) -------------------


@pytest.mark.parametrize("gemeinde_schluessel", ["city", "town", "municipality", "village", "township", "hamlet"])
def test_gemeinde_faellt_durch_alle_nominatim_schluessel_zurueck(gemeinde_schluessel):
    address = {"state": "Bayern", "country_code": "de"}
    address[gemeinde_schluessel] = "Kleindorf"
    result = parse_nominatim_results([_result(address=address)])
    assert result.geo_municipality == "Kleindorf"


def test_bevorzugt_city_vor_town_wenn_beides_vorhanden():
    address = {"city": "Großstadt", "town": "sollte-ignoriert-werden", "state": "Bayern", "country_code": "de"}
    result = parse_nominatim_results([_result(address=address)])
    assert result.geo_municipality == "Großstadt"


# --- Einzugsgebiet -----------------------------------------------------------


def test_alle_16_bundeslaender_sind_im_default_einzugsgebiet():
    for state in GERMAN_STATES:
        result = parse_nominatim_results([_result(address={"state": state, "city": "X", "country_code": "de"})])
        assert result.in_service_area is True, state


def test_ausserhalb_des_einzugsgebiets_per_default():
    result = parse_nominatim_results([_result(address={"state": "Tirol", "city": "Innsbruck", "country_code": "at"})])
    assert result.geo_state == "Tirol"
    assert result.geo_country == "AT"
    assert result.in_service_area is False


def test_benutzerdefiniertes_einzugsgebiet_fuer_pilot_rollout():
    result_in = parse_nominatim_results(
        [_result(address={"state": "Bayern", "city": "X", "country_code": "de"})], service_area_states={"Bayern"}
    )
    result_out = parse_nominatim_results(
        [_result(address={"state": "Hamburg", "city": "X", "country_code": "de"})], service_area_states={"Bayern"}
    )
    assert result_in.in_service_area is True
    assert result_out.in_service_area is False


def test_fehlende_koordinaten_werden_nicht_erraten():
    result = parse_nominatim_results([_result(lat=None, lon=None)])
    assert result.lat is None
    assert result.lon is None


# --- parse_service_area_states (SERVICE_AREA_STATES-Env, Fund 2026-08-17) --
# Fund: ein leerer Wert bedeutete schon immer "alle 16 Bundesländer", aber
# das Wort "alle" selbst (dieselbe Sentinel-Konvention wie die Tab-/Status-
# Filter in app/admin.py) wurde nirgends erkannt - SERVICE_AREA_STATES=alle
# wurde als Ein-Element-Menge {"alle"} geparst, auf die kein echtes
# Bundesland je passt. in_service_area wäre für JEDE Adresse still False
# gewesen, ohne jede Fehlermeldung (s. docs/FUNDE.md).


def test_leerer_wert_bedeutet_alle_16_bundeslaender():
    assert parse_service_area_states("") == set(GERMAN_STATES)
    assert parse_service_area_states("   ") == set(GERMAN_STATES)


def test_alle_sentinel_bedeutet_alle_16_bundeslaender():
    assert parse_service_area_states("alle") == set(GERMAN_STATES)
    assert parse_service_area_states("Alle") == set(GERMAN_STATES)  # Groß-/Kleinschreibung ist hier kein Raten, nur Toleranz gegenüber Tippgewohnheit


def test_kommagetrennte_echte_bundeslaender_werden_uebernommen():
    assert parse_service_area_states("Bayern, Hessen") == {"Bayern", "Hessen"}


def test_unbekannter_bundesland_name_wirft_statt_still_leer_zu_werden():
    # Der eigentliche Fehler war nicht "alle" selbst, sondern dass JEDER
    # unbekannte Wert (auch ein Tippfehler wie "Bayen") stillschweigend zu
    # einem Filter wurde, der auf nichts passt - deshalb eine echte Prüfung
    # gegen GERMAN_STATES, nicht nur eine Sonderbehandlung für "alle".
    with pytest.raises(ValueError, match="Bayen"):
        parse_service_area_states("Bayen")


def test_ein_unbekannter_wert_unter_sonst_gueltigen_wirft_ebenfalls():
    with pytest.raises(ValueError, match="Hesen"):
        parse_service_area_states("Bayern, Hesen")


def test_service_area_states_wird_beim_modulimport_ausgewertet_und_bricht_beim_start_ab(monkeypatch):
    # "bricht die Anwendung beim Start ab" heißt hier: beim Modul-Import,
    # nicht erst beim ersten geocode()-Aufruf (dieselbe Konvention wie
    # app/config.py: MAX_EMAILS_PER_DAY etc.). Ein frischer Reload mit
    # ungültigem Wert im Environment muss deshalb schon beim Import scheitern.
    import importlib

    import app.geocoding as geocoding_module

    monkeypatch.setenv("SERVICE_AREA_STATES", "Bayen")
    monkeypatch.setenv("NOMINATIM_USER_AGENT", "test")
    try:
        with pytest.raises(RuntimeError, match="SERVICE_AREA_STATES"):
            importlib.reload(geocoding_module)
    finally:
        monkeypatch.delenv("SERVICE_AREA_STATES", raising=False)
        importlib.reload(geocoding_module)  # sauberen Modulzustand für nachfolgende Tests wiederherstellen
