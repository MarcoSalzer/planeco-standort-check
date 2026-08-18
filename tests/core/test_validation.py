from app.core.validation import validate_submission


def _valid_kwargs(**overrides):
    kwargs = dict(
        street="Musterstraße 12",
        city="Hamburg",
        email="tom.ahrens@example.com",
        postal_code="20095",
        contact_time_preference="vormittags",
        privacy_accepted=True,
    )
    kwargs.update(overrides)
    return kwargs


def test_vollstaendige_eingabe_hat_keine_fehler():
    assert validate_submission(**_valid_kwargs()) == {}


def test_fehlende_pflichtfelder():
    errors = validate_submission(**_valid_kwargs(street="", city="   ", email=None, privacy_accepted=False))
    assert set(errors) == {"street", "city", "email", "privacy_accepted"}


def test_ungueltige_email_syntax():
    errors = validate_submission(**_valid_kwargs(email="nicht-valide"))
    assert "email" in errors


def test_ort_nur_ziffern_deutet_auf_plz_ort_vertauschung_hin():
    errors = validate_submission(**_valid_kwargs(city="20095"))
    assert "city" in errors


def test_ort_mit_ziffern_und_buchstaben_ist_kein_fehler():
    # Echte Ortsnamen mit Ziffern existieren (z.B. Nummernzusätze in
    # zusammengesetzten Namen) - nur eine REINE Ziffernfolge ist der
    # Verdachtsfall, nicht jede Ziffer im Ortsnamen.
    errors = validate_submission(**_valid_kwargs(city="Sankt Peter-Ording 3"))
    assert "city" not in errors


def test_plz_zu_kurz_ist_ein_fehler():
    errors = validate_submission(**_valid_kwargs(postal_code="123"))
    assert "postal_code" in errors


def test_plz_zu_lang_ist_ein_fehler():
    errors = validate_submission(**_valid_kwargs(postal_code="12345678901"))
    assert "postal_code" in errors


def test_plz_vierstellig_oesterreichisch_ist_kein_fehler():
    errors = validate_submission(**_valid_kwargs(postal_code="1010"))
    assert "postal_code" not in errors


def test_plz_alphanumerisch_ist_kein_fehler():
    errors = validate_submission(**_valid_kwargs(postal_code="SW1A1AA"))
    assert "postal_code" not in errors


def test_plz_optional_leer_ist_kein_fehler():
    errors = validate_submission(**_valid_kwargs(postal_code=""))
    assert "postal_code" not in errors


def test_plz_none_ist_kein_fehler():
    errors = validate_submission(**_valid_kwargs(postal_code=None))
    assert "postal_code" not in errors


def test_ungueltige_contact_time_preference():
    errors = validate_submission(**_valid_kwargs(contact_time_preference="mittags"))
    assert "contact_time_preference" in errors


def test_leere_contact_time_preference_ist_kein_fehler():
    errors = validate_submission(**_valid_kwargs(contact_time_preference=""))
    assert "contact_time_preference" not in errors


def test_abends_ist_eine_gueltige_contact_time_preference():
    errors = validate_submission(**_valid_kwargs(contact_time_preference="abends"))
    assert "contact_time_preference" not in errors


def test_privacy_nicht_akzeptiert():
    errors = validate_submission(**_valid_kwargs(privacy_accepted=False))
    assert errors["privacy_accepted"]
