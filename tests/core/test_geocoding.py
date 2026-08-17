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
    result = parse_nominatim_results([], expected_postal_code=None, expected_city="Hamburg")
    assert result.status == "nicht_gefunden"
    assert result.candidate_count == 0
    assert result.in_service_area is None
    assert result.geo_state_unresolved is False
    assert result.raw == {"results": [], "auswahl": {"kandidaten_gesamt": 0, "eingestuft_als": "keine_treffer", "gewaehlter_index": None}}


def test_ein_treffer_ist_ok_und_eindeutig():
    result = parse_nominatim_results([_result()], expected_postal_code="20095", expected_city="Hamburg")
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
    # hoch) und "Reichstagskuppel" (importance niedrig) an derselben Stelle,
    # mit leicht unterschiedlicher PLZ (zwei Adressobjekte am selben
    # Gebäudekomplex) - deshalb hier expected_postal_code=None, die PLZ-
    # Prüfung ist nicht Gegenstand dieses Tests (s. eigene Tests weiter unten).
    gebaeude = _result(
        importance=0.549, lat="52.5186538", lon="13.3761015",
        address={"tourism": "Reichstagsgebäude", "city": "Berlin", "ISO3166-2-lvl4": "DE-BE", "postcode": "11011", "country_code": "de"},
    )
    kuppel = _result(
        importance=0.205, lat="52.5185931", lon="13.3761064",
        address={"tourism": "Reichstagskuppel", "city": "Berlin", "ISO3166-2-lvl4": "DE-BE", "postcode": "10557", "country_code": "de"},
    )
    result = parse_nominatim_results([kuppel, gebaeude], expected_postal_code=None, expected_city="Berlin")  # absichtlich in "falscher" Reihenfolge
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
    result = parse_nominatim_results(nebenfunde + [rathaus], expected_postal_code="80331", expected_city="München")
    assert result.status == "ok"
    assert result.raw["auswahl"]["gewaehlter_index"] == 4  # das Rathaus steht als letztes in der Liste


def test_lindenweg_neustadt_mit_wortlaut_eingabe_ist_jetzt_nicht_gefunden():
    # Verhaltensänderung (Marco, 2026-08-18, s. docs/FUNDE.md): Nominatims
    # drei "Neustadt"-Kandidaten aus dem Testfall der Aufgabe heißen in
    # Wirklichkeit "Neustadt im Schwarzwald"/"Neustadt in Holstein"/
    # "Neustadt in Sachsen" - keiner davon entspricht dem exakt eingegebenen
    # Ortsnamen "Neustadt" nach dem neuen Abgleich (derselbe strenge
    # lower/trim-Vergleich wie beim Duplikat-Vergleich, keine Teilstring-
    # Toleranz). Vorher wurde jeder Kandidat ungeprüft akzeptiert, das
    # Ergebnis war 'mehrdeutig'. Jetzt: kein einziger Kandidat besteht die
    # Adress-Prüfung -> 'nicht_gefunden'. Bewusst NICHT nachträglich auf
    # Teilstring-Toleranz aufgeweicht - das wäre derselbe Fehlertyp wie der
    # Bayern-Weiler-Fund (ein zu großzügiger Abgleich), nur eine Stufe
    # vorsichtiger versteckt.
    kandidaten = [
        _result(address={"city": "Neustadt im Schwarzwald", "state": "Baden-Württemberg", "postcode": "79822", "country_code": "de"}),
        _result(address={"city": "Neustadt in Holstein", "state": "Schleswig-Holstein", "postcode": "23730", "country_code": "de"}),
        _result(address={"city": "Neustadt in Sachsen", "state": "Sachsen", "postcode": "01844", "country_code": "de"}),
    ]
    result = parse_nominatim_results(kandidaten, expected_postal_code=None, expected_city="Neustadt")
    assert result.status == "nicht_gefunden"
    assert result.candidate_count == 0
    assert result.raw["auswahl"]["eingestuft_als"] == "kein_passender_treffer"


def test_lindenweg_neustadt_bleibt_mehrdeutig_bei_exakt_uebereinstimmendem_ortsnamen():
    # Der ursprüngliche Testfall aus der Aufgabe bleibt sinngemäß gültig,
    # wenn der eingegebene Ortsname exakt einem von mehreren real
    # existierenden, aber unterschiedlichen Orten entspricht (mehrere echte
    # deutsche Orte heißen exakt "Neustadt", in unterschiedlichen
    # Bundesländern) - muss weiterhin mehrdeutig bleiben.
    kandidaten = [
        _result(address={"city": "Neustadt", "state": "Baden-Württemberg", "postcode": "79822", "country_code": "de"}),
        _result(address={"city": "Neustadt", "state": "Schleswig-Holstein", "postcode": "23730", "country_code": "de"}),
        _result(address={"city": "Neustadt", "state": "Sachsen", "postcode": "01844", "country_code": "de"}),
    ]
    result = parse_nominatim_results(kandidaten, expected_postal_code=None, expected_city="Neustadt")
    assert result.status == "mehrdeutig"
    assert result.candidate_count == 3
    assert result.geo_state is None
    assert result.in_service_area is None
    assert result.raw["auswahl"] == {"kandidaten_gesamt": 3, "eingestuft_als": "widerspruechlich", "gewaehlter_index": None}


def test_mehrdeutig_zaehlt_echte_orte_nicht_rohe_trefferzahl():
    # 4 rohe Treffer, aber nur 2 wirklich verschiedene Orte -> candidate_count
    # soll 2 sein ("2 mögliche Orte"), nicht 4 - sonst genau dieselbe
    # Irreführung, die der Fix eigentlich beheben soll. Beide Orte heißen
    # "Neustadt" (Bedingung für den neuen Adress-Abgleich), liegen aber in
    # unterschiedlichen Bundesländern - genau der Fall, der mehrdeutig sein muss.
    ort_a = {"city": "Neustadt", "state": "Bayern", "country_code": "de"}
    ort_b = {"town": "Neustadt", "state": "Hessen", "country_code": "de"}
    kandidaten = [_result(address=ort_a), _result(address=ort_a), _result(address=ort_b), _result(address=ort_b)]
    result = parse_nominatim_results(kandidaten, expected_postal_code=None, expected_city="Neustadt")
    assert result.status == "mehrdeutig"
    assert result.candidate_count == 2


def test_unterschiedliche_gemeinde_bei_gleichem_bundesland_ist_auch_mehrdeutig():
    # Beide Kandidaten bestehen den Ortsnamen-Abgleich über "village":
    # "Neustadt" (derselbe eingegebene Ortsname), lösen aber zu
    # unterschiedlichen Gemeinden auf: Kandidat 1 hat zusätzlich eine
    # "municipality" (übergeordnete Verwaltungsgemeinschaft), die bei der
    # Gemeinde-Extraktion Vorrang vor "village" hat (_GEMEINDE_SCHLUESSEL) -
    # dieselbe reale Uneinheitlichkeit, die schon die Gemeinde-Schlüssel-
    # Fallback-Tests unten abdecken.
    kandidaten = [
        _result(address={"village": "Neustadt", "municipality": "Amt Nordwest", "state": "Bayern", "country_code": "de"}),
        _result(address={"village": "Neustadt", "state": "Bayern", "country_code": "de"}),
    ]
    result = parse_nominatim_results(kandidaten, expected_postal_code=None, expected_city="Neustadt")
    assert result.status == "mehrdeutig"


# --- candidate_summaries: Kandidatenliste für die Detailansicht (Block d) --
# (unverändert - candidate_summaries() bekommt bereits als mehrdeutig
# eingestufte Kandidaten übergeben, macht selbst keinen Adress-Abgleich.)


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
    result = parse_nominatim_results([_result(address=address)], expected_postal_code=None, expected_city=erwartetes_bundesland)
    assert result.geo_state == erwartetes_bundesland
    assert result.in_service_area is True
    assert result.geo_state_unresolved is False


def test_alle_16_iso_codes_sind_korrekt_zugeordnet():
    assert set(ISO_3166_2_TO_STATE.values()) == set(GERMAN_STATES)
    assert len(ISO_3166_2_TO_STATE) == 16


def test_state_feld_hat_vorrang_vor_iso_code_falls_beide_da_sind():
    address = {"city": "Irgendwo", "state": "Bayern", "ISO3166-2-lvl4": "DE-TH", "country_code": "de"}
    result = parse_nominatim_results([_result(address=address)], expected_postal_code=None, expected_city="Irgendwo")
    assert result.geo_state == "Bayern"


def test_auslaendischer_iso_code_wird_nicht_als_deutsches_bundesland_gewertet():
    address = {"city": "Wien", "ISO3166-2-lvl4": "AT-9", "country_code": "at"}
    result = parse_nominatim_results([_result(address=address)], expected_postal_code=None, expected_city="Wien")
    assert result.geo_state is None
    assert result.geo_state_unresolved is True


# --- "erkennbar bleibt": geo_state_unresolved -------------------------------


def test_fehlendes_bundesland_bei_sonst_eindeutigem_treffer_ist_erkennbar_markiert():
    address = {"city": "Irgendwo", "country_code": "de"}  # weder state noch ISO3166-2-lvl4
    result = parse_nominatim_results([_result(address=address)], expected_postal_code=None, expected_city="Irgendwo")
    assert result.status == "ok"
    assert result.geo_state is None
    assert result.geo_state_unresolved is True
    assert result.in_service_area is None  # "wissen wir nicht", nicht "liegt draußen"


def test_aufgeloestes_bundesland_ist_nicht_als_unresolved_markiert():
    result = parse_nominatim_results([_result()], expected_postal_code="20095", expected_city="Hamburg")
    assert result.geo_state_unresolved is False


def test_nicht_gefunden_und_mehrdeutig_sind_nicht_unresolved_markiert():
    # geo_state_unresolved gilt nur für den "eindeutiger Treffer, aber kein
    # Bundesland ermittelbar"-Fall, nicht für die anderen beiden Status.
    assert parse_nominatim_results([], expected_postal_code=None, expected_city="X").geo_state_unresolved is False
    widerspruch = [
        _result(address={"state": "Bayern", "city": "Neustadt", "country_code": "de"}),
        _result(address={"state": "Hessen", "city": "Neustadt", "country_code": "de"}),
    ]
    assert parse_nominatim_results(widerspruch, expected_postal_code=None, expected_city="Neustadt").geo_state_unresolved is False


# --- Gemeinde-Schlüssel-Fallback (unverändert von vorher) -------------------


@pytest.mark.parametrize("gemeinde_schluessel", ["city", "town", "municipality", "village", "township", "hamlet"])
def test_gemeinde_faellt_durch_alle_nominatim_schluessel_zurueck(gemeinde_schluessel):
    address = {"state": "Bayern", "country_code": "de"}
    address[gemeinde_schluessel] = "Kleindorf"
    result = parse_nominatim_results([_result(address=address)], expected_postal_code=None, expected_city="Kleindorf")
    assert result.geo_municipality == "Kleindorf"


def test_bevorzugt_city_vor_town_wenn_beides_vorhanden():
    address = {"city": "Großstadt", "town": "sollte-ignoriert-werden", "state": "Bayern", "country_code": "de"}
    result = parse_nominatim_results([_result(address=address)], expected_postal_code=None, expected_city="Großstadt")
    assert result.geo_municipality == "Großstadt"


# --- Einzugsgebiet -----------------------------------------------------------


def test_alle_16_bundeslaender_sind_im_default_einzugsgebiet():
    for state in GERMAN_STATES:
        result = parse_nominatim_results(
            [_result(address={"state": state, "city": "X", "country_code": "de"})], expected_postal_code=None, expected_city="X"
        )
        assert result.in_service_area is True, state


def test_ausserhalb_des_einzugsgebiets_per_default():
    result = parse_nominatim_results(
        [_result(address={"state": "Tirol", "city": "Innsbruck", "country_code": "at"})],
        expected_postal_code=None, expected_city="Innsbruck",
    )
    assert result.geo_state == "Tirol"
    assert result.geo_country == "AT"
    assert result.in_service_area is False


def test_land_hat_vorrang_vor_bundesland_wien_ohne_state_feld_loest_trotzdem_aus():
    # Regression (Marco, 2026-08-18, s. docs/FUNDE.md): Wien liefert wie die
    # deutschen Stadtstaaten KEIN "state"-Feld, nur "ISO3166-2-lvl4": "AT-9" -
    # eine deutschlandspezifische Codetabelle (ISO_3166_2_TO_STATE) kann das
    # nicht auflösen. country_code entscheidet jetzt VORRANGIG: ist er nicht
    # "de", ist die Adresse außerhalb, unabhängig davon, ob ein Bundesland
    # ermittelbar ist. Keine Codetabelle pro Land nötig.
    result = parse_nominatim_results(
        [_result(address={"city": "Wien", "ISO3166-2-lvl4": "AT-9", "postcode": "1010", "country_code": "at"})],
        expected_postal_code="1010", expected_city="Wien",
    )
    assert result.status == "ok"
    assert result.geo_state is None  # weiterhin nicht auflösbar - ehrlich, nicht erraten
    assert result.geo_country == "AT"
    assert result.in_service_area is False  # aber das Land allein reicht schon


def test_deutsche_adresse_ohne_ermittelbares_bundesland_bleibt_unbekannt_nicht_falsch():
    # Kehrseite des vorigen Tests: fehlt bei einer INLÄNDISCHEN Adresse das
    # Bundesland (weder state noch ISO-Code), bleibt in_service_area
    # weiterhin None ("wissen wir nicht") statt False - country_code="de"
    # verhindert das fälschliche Auslands-Signal.
    result = parse_nominatim_results(
        [_result(address={"city": "Irgendwo", "country_code": "de"})],
        expected_postal_code=None, expected_city="Irgendwo",
    )
    assert result.geo_state is None
    assert result.geo_country == "DE"
    assert result.in_service_area is None


def test_benutzerdefiniertes_einzugsgebiet_fuer_pilot_rollout():
    result_in = parse_nominatim_results(
        [_result(address={"state": "Bayern", "city": "X", "country_code": "de"})],
        expected_postal_code=None, expected_city="X", service_area_states={"Bayern"},
    )
    result_out = parse_nominatim_results(
        [_result(address={"state": "Hamburg", "city": "X", "country_code": "de"})],
        expected_postal_code=None, expected_city="X", service_area_states={"Bayern"},
    )
    assert result_in.in_service_area is True
    assert result_out.in_service_area is False


def test_fehlende_koordinaten_werden_nicht_erraten():
    result = parse_nominatim_results([_result(lat=None, lon=None)], expected_postal_code="20095", expected_city="Hamburg")
    assert result.lat is None
    assert result.lon is None


# --- Abgleich Eingabe vs. Ergebnis (Marco, 2026-08-18, s. docs/FUNDE.md) ----
# countrycodes=de wurde aus app/geocoding.py entfernt (die Ländereinschrän-
# kung gehört in SERVICE_AREA_STATES/in_service_area, nicht in die Anfrage -
# sonst kann der Auslandspfad nie auslösen). Die Suche läuft jetzt weltweit,
# ohne Prüfung gegen die Eingabe hätte das genau den Fehlalarm reproduziert,
# den es beheben soll: für "Stephansplatz 1, 1010 Wien" lieferte Nominatim
# unscharf einen Weiler namens "Wien" bei Inzell, Bayern (PLZ 83334 - eine
# vierstellige, in Deutschland gar nicht existente PLZ, nie gegen die
# Eingabe geprüft). Ortsname ist ein hartes Kriterium (kein Kandidat ohne
# passenden Ort). PLZ ist weicher (Marco, 2026-08-18, zweite Korrekturrunde):
# FEHLT sie in der Antwort, ist das kein Widerspruch (Verwaltungsgrenzen-
# Objekte liefern grundsätzlich keine PLZ - das hätte sonst den Ortsebene-
# Rückfall aus Punkt 1 für seinen eigenen Zielfall unbrauchbar gemacht).
# WEICHT sie tatsächlich ab, wird der Treffer nicht verworfen, sondern als
# 'plz_abweichend' markiert (ein Interessent mit vertippter, optionaler PLZ
# soll nicht auf Rot landen) - "kein Wert" und "falscher Wert" dürfen nicht
# gleich behandelt werden, s. docs/FUNDE.md.


def test_regression_wien_weiler_in_bayern_wird_als_plz_abweichend_markiert_nicht_verworfen():
    # Nachgebaut aus dem echten Live-Fund (docs/FUNDE.md): der Ortsname
    # "Wien" passt zufällig exakt (der Weiler heißt tatsächlich so), die PLZ
    # nicht. Der Treffer wird NICHT verworfen (das wäre wieder "kein Wert"
    # und "falscher Wert" gleich behandeln) - aber auch nicht als 'ok'
    # bestätigt: 'plz_abweichend' macht die Abweichung für Sales sichtbar,
    # statt sie zu verschweigen oder den ganzen Treffer wegzuwerfen.
    weiler = _result(
        address={"hamlet": "Wien", "village": "Gschwall", "state": "Bayern", "postcode": "83334", "country_code": "de"},
    )
    result = parse_nominatim_results([weiler], expected_postal_code="1010", expected_city="Wien")
    assert result.status == "plz_abweichend"
    assert result.geo_postal_code == "83334"
    assert result.geo_state == "Bayern"


def test_fehlende_plz_in_der_antwort_ist_kein_widerspruch_bleibt_ok():
    # Groß Grönau (docs/FUNDE.md): Verwaltungsgrenzen-Objekte (Dörfer,
    # Gemeinden) liefern grundsätzlich keine PLZ - das darf den sonst
    # eindeutigen Treffer nicht zu 'plz_abweichend' oder gar 'nicht_gefunden'
    # machen. NICHT nachträglich aufweichen, sonst wiederholt sich genau der
    # Fund von docs/FUNDE.md (der Ortsebene-Rückfall wäre für seinen
    # eigenen Zielfall wieder unbrauchbar).
    kandidat = _result(
        address={"village": "Groß Grönau", "municipality": "Lauenburgische Seen", "state": "Schleswig-Holstein", "country_code": "de"},
    )
    result = parse_nominatim_results([kandidat], expected_postal_code="23627", expected_city="Groß Grönau")
    assert result.status == "ok"
    assert result.geo_postal_code is None


def test_ortsname_mismatch_verwirft_sonst_passenden_kandidaten():
    kandidat = _result(address={"city": "Hamburg", "state": "Hamburg", "postcode": "20095", "country_code": "de"})
    result = parse_nominatim_results([kandidat], expected_postal_code="20095", expected_city="Bremen")
    assert result.status == "nicht_gefunden"


def test_ortsname_abgleich_ist_exakt_keine_teilstring_toleranz():
    kandidat = _result(address={"city": "Neustadt im Schwarzwald", "state": "Baden-Württemberg", "postcode": "79822", "country_code": "de"})
    result = parse_nominatim_results([kandidat], expected_postal_code=None, expected_city="Neustadt")
    assert result.status == "nicht_gefunden"


def test_ortsname_abgleich_ignoriert_gross_kleinschreibung_und_leerraum():
    # Dieselbe Normalisierung wie der Duplikat-Vergleich (lower/trim,
    # app/submission.py::_find_dedup_candidate) - keine strengere Prüfung
    # als dort.
    kandidat = _result(address={"city": "Hamburg", "state": "Hamburg", "postcode": "20095", "country_code": "de"})
    result = parse_nominatim_results([kandidat], expected_postal_code="20095", expected_city="  hamburg  ")
    assert result.status == "ok"


def test_keine_plz_eingegeben_ueberspringt_die_plz_pruefung():
    kandidat = _result(address={"city": "Hamburg", "state": "Hamburg", "postcode": "20095", "country_code": "de"})
    result = parse_nominatim_results([kandidat], expected_postal_code=None, expected_city="Hamburg")
    assert result.status == "ok"


def test_ortsname_darf_ueber_jedes_gemeinde_feld_uebereinstimmen():
    # Groß Grönau (Konzept-Fund, docs/FUNDE.md): Nominatim liefert den Ort
    # unter "village", nicht unter "city" - der Abgleich darf sich nicht
    # auf ein einzelnes Feld verlassen.
    kandidat = _result(
        address={"village": "Groß Grönau", "municipality": "Lauenburgische Seen", "state": "Schleswig-Holstein", "postcode": "23627", "country_code": "de"},
    )
    result = parse_nominatim_results([kandidat], expected_postal_code="23627", expected_city="Groß Grönau")
    assert result.status == "ok"
    assert result.geo_state == "Schleswig-Holstein"


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
