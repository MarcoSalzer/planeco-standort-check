import pytest

from app.core.geocoding import GERMAN_STATES, parse_nominatim_results


def _result(**overrides) -> dict:
    base = {
        "place_id": 12345,
        "lat": "53.5510846",
        "lon": "9.9936818",
        "display_name": "Musterstraße 12, Hamburg, Deutschland",
        "address": {
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


def test_leere_liste_ist_nicht_gefunden():
    result = parse_nominatim_results([])
    assert result.status == "nicht_gefunden"
    assert result.candidate_count == 0
    assert result.raw == []
    assert result.in_service_area is None


def test_mehrere_treffer_ist_mehrdeutig():
    results = [_result(place_id=1), _result(place_id=2), _result(place_id=3)]
    result = parse_nominatim_results(results)
    assert result.status == "mehrdeutig"
    assert result.candidate_count == 3
    assert result.geo_state is None  # bei mehrdeutig wird nichts einzelnes "gewonnen"
    assert result.raw == results


def test_ein_treffer_ist_ok_mit_allen_feldern():
    result = parse_nominatim_results([_result()])
    assert result.status == "ok"
    assert result.candidate_count == 1
    assert result.lat == pytest.approx(53.5510846)
    assert result.lon == pytest.approx(9.9936818)
    assert result.geo_state == "Hamburg"
    assert result.geo_municipality == "Hamburg"
    assert result.geo_country == "DE"
    assert result.in_service_area is True  # Hamburg ist Teil des Default-Einzugsgebiets


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


def test_ausserhalb_des_einzugsgebiets_per_default_alle_16_laender():
    result = parse_nominatim_results([_result(address={"state": "Tirol", "country_code": "at"})])
    assert result.geo_state == "Tirol"
    assert result.geo_country == "AT"
    assert result.in_service_area is False


def test_kein_bundesland_ermittelbar_ist_none_nicht_false():
    result = parse_nominatim_results([_result(address={"country_code": "de"})])
    assert result.geo_state is None
    assert result.in_service_area is None  # "wissen wir nicht", nicht "liegt draußen"


def test_alle_16_bundeslaender_sind_im_default_einzugsgebiet():
    for state in GERMAN_STATES:
        result = parse_nominatim_results([_result(address={"state": state, "country_code": "de"})])
        assert result.in_service_area is True, state


def test_benutzerdefiniertes_einzugsgebiet_fuer_pilot_rollout():
    # Konzept §0: SERVICE_AREA_STATES als Pilot-Override auf einzelne Länder.
    result_in = parse_nominatim_results(
        [_result(address={"state": "Bayern", "country_code": "de"})], service_area_states={"Bayern"}
    )
    result_out = parse_nominatim_results(
        [_result(address={"state": "Hamburg", "country_code": "de"})], service_area_states={"Bayern"}
    )
    assert result_in.in_service_area is True
    assert result_out.in_service_area is False


def test_fehlende_koordinaten_werden_nicht_erraten():
    result = parse_nominatim_results([_result(lat=None, lon=None)])
    assert result.lat is None
    assert result.lon is None
