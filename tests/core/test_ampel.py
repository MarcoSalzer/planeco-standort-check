import pytest

from app.core.ampel import ampel


def _base(**overrides):
    defaults = dict(
        is_spam=False,
        spam_reason=None,
        in_service_area=True,
        geocode_status="ok",
        geo_state="Sachsen",
        geo_country=None,
        geocode_candidate_count=None,
        phone_raw="0170 5551234",
        phone_valid=True,
        postal_code="20095",
    )
    defaults.update(overrides)
    return defaults


def test_regel1_spam_schlaegt_alles_andere():
    result = ampel(
        **_base(is_spam=True, spam_reason="honeypot_gefuellt", geocode_status="nicht_gefunden")
    )
    assert result.farbe == "schwarz"
    assert "Bot-Verdacht" in result.grund


def test_regel1_spam_ohne_grund_bleibt_lesbar():
    result = ampel(**_base(is_spam=True, spam_reason=None))
    assert result.farbe == "schwarz"
    assert result.grund == "Spamverdacht"


def test_regel2_ausserhalb_deutschlands_zeigt_bundesland():
    result = ampel(**_base(in_service_area=False, geo_state="Tirol"))
    assert result.farbe == "rot"
    assert "Tirol" in result.grund


def test_regel2_ausserhalb_deutschlands_faellt_ohne_bundesland_auf_land_zurueck():
    result = ampel(**_base(in_service_area=False, geo_state=None, geo_country="AT"))
    assert result.farbe == "rot"
    assert "AT" in result.grund


def test_regel3_nicht_gefunden():
    result = ampel(**_base(geocode_status="nicht_gefunden"))
    assert result.farbe == "rot"
    # Kein unterstellter Tippfehler mehr (Marco, 2026-08-18, nach dem
    # OSM-Fund in docs/FUNDE.md: die Schreibweise war bei Groß Grönau
    # korrekt, nur die Straße fehlte im Kartendienst).
    assert result.grund == "Adresse im Kartendienst nicht gefunden"
    assert "Schreibweise" not in result.grund


def test_nur_ort_ist_gelb_und_benennt_die_kartenluecke():
    result = ampel(**_base(geocode_status="nur_ort"))
    assert result.farbe == "gelb"
    assert result.grund == "Ort bestätigt, Straße nicht in der Karte gefunden"


def test_regel4_fehlgeschlagen_ist_grau_nicht_gelb():
    result = ampel(**_base(geocode_status="fehlgeschlagen"))
    assert result.farbe == "grau"


def test_regel5_offen_ist_grau_mit_pruefung_laeuft():
    result = ampel(**_base(geocode_status="offen"))
    assert result.farbe == "grau"
    assert result.grund == "Prüfung läuft"


def test_entfaellt_ist_grau_nicht_faelschlich_gruen():
    result = ampel(**_base(geocode_status="entfaellt"))
    assert result.farbe == "grau"


def test_simuliert_ist_grau_und_benennt_den_testmodus():
    # Fund 17.08.: fehlte hier, ampel() warf für 'simuliert' einen
    # ValueError - ein einziger Dry-Run-Lead legte die ganze Liste lahm.
    result = ampel(**_base(geocode_status="simuliert"))
    assert result.farbe == "grau"
    assert "Testmodus" in result.grund


def test_regel6_mehrdeutig_mit_kandidatenzahl():
    result = ampel(**_base(geocode_status="mehrdeutig", geocode_candidate_count=3))
    assert result.farbe == "gelb"
    assert "3" in result.grund


def test_regel6_mehrdeutig_ohne_kandidatenzahl_bleibt_lesbar():
    result = ampel(**_base(geocode_status="mehrdeutig", geocode_candidate_count=None))
    assert result.farbe == "gelb"
    assert "mehrdeutig" in result.grund.lower()


def test_regel7_kein_telefon_angegeben():
    result = ampel(**_base(phone_raw=None, phone_valid=False))
    assert result.farbe == "gelb"
    assert result.grund == "Nur per E-Mail erreichbar"


def test_regel8_telefon_angegeben_aber_unlesbar_zeigt_rohwert():
    result = ampel(**_base(phone_raw="123", phone_valid=False))
    assert result.farbe == "gelb"
    assert "123" in result.grund


def test_regel9_keine_plz():
    result = ampel(**_base(postal_code=None))
    assert result.farbe == "gelb"


def test_regel10_vollstaendig():
    result = ampel(**_base())
    assert result.farbe == "gruen"
    assert result.grund == "Vollständig"


def test_prioritaet_spam_schlaegt_auslandsregel():
    result = ampel(**_base(is_spam=True, in_service_area=False))
    assert result.farbe == "schwarz"


def test_prioritaet_ausland_schlaegt_geocode_status_regeln():
    result = ampel(**_base(in_service_area=False, geocode_status="mehrdeutig"))
    assert result.farbe == "rot"


def test_unbekannter_geocode_status_wirft_fehler_statt_zu_raten():
    with pytest.raises(ValueError):
        ampel(**_base(geocode_status="???"))
