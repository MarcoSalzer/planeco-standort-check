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


def test_plz_muss_fuenfstellig_sein_wenn_gefuellt():
    errors = validate_submission(**_valid_kwargs(postal_code="123"))
    assert "postal_code" in errors


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
