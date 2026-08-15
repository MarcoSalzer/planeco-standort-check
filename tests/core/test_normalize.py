import pytest

from app.core.normalize import normalize_email, normalize_name, normalize_phone


@pytest.mark.parametrize(
    "raw, expected_e164",
    [
        ("+49 40 / 123 456", "+4940123456"),
        ("0170 5551234", "+491705551234"),
        ("040 55512345", "+494055512345"),
        ("004940123456", "+4940123456"),
        ("0451 9988776", "+494519988776"),
    ],
)
def test_normalize_phone_valid_formats(raw, expected_e164):
    e164, valid = normalize_phone(raw)
    assert e164 == expected_e164
    assert valid is True


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "abc",
        "123",   # zu kurz, keine Landesvorwahl erkennbar
        "0123",  # nach Normalisierung zu kurz fuer eine echte Nummer
    ],
)
def test_normalize_phone_unparsable_stays_conservative(raw):
    e164, valid = normalize_phone(raw)
    assert e164 is None
    assert valid is False


def test_normalize_phone_passes_through_other_country_codes():
    e164, valid = normalize_phone("+43 664 1234567")
    assert e164 == "+436641234567"
    assert valid is True


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  Tom.Ahrens@Example.COM ", "tom.ahrens@example.com"),
        ("test@Domain.de", "test@domain.de"),
    ],
)
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw, expected_name, expected_normalized",
    [
        ("TOM AHRENS", "Tom Ahrens", True),
        ("tom ahrens", "Tom Ahrens", True),
        ("müller-lüdenscheidt", "Müller-Lüdenscheidt", True),
        ("van der berg", "van der berg", False),
        ("VAN DER BERG", "VAN DER BERG", False),
        ("o'brien", "O'Brien", True),
        ("McDonald", "McDonald", False),
        ("O'Brien", "O'Brien", False),
        ("di Marco", "di Marco", False),
    ],
)
def test_normalize_name(raw, expected_name, expected_normalized):
    name, was_normalized = normalize_name(raw)
    assert name == expected_name
    assert was_normalized is expected_normalized
