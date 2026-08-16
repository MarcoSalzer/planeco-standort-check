import pytest

from app.core.spam import detect_spam


def test_honeypot_gefuellt_gewinnt_immer():
    is_spam, reason = detect_spam(honeypot_value="ich bin ein bot", elapsed_seconds=10, message=None)
    assert is_spam is True
    assert reason == "honeypot_gefuellt"


def test_leeres_honeypot_ist_kein_spam_signal():
    is_spam, reason = detect_spam(honeypot_value="", elapsed_seconds=10, message=None)
    assert is_spam is False
    assert reason is None


def test_zu_schnell_abgesendet():
    is_spam, reason = detect_spam(honeypot_value=None, elapsed_seconds=1.2, message=None)
    assert is_spam is True
    assert reason == "zu_schnell_abgesendet"


def test_genau_an_der_schwelle_ist_kein_spam():
    is_spam, reason = detect_spam(honeypot_value=None, elapsed_seconds=3.0, message=None)
    assert is_spam is False


def test_unbekannte_verstrichene_zeit_wird_nicht_gewertet():
    is_spam, reason = detect_spam(honeypot_value=None, elapsed_seconds=None, message=None)
    assert is_spam is False


@pytest.mark.parametrize(
    "message",
    [
        "Schauen Sie mal hier: https://spam.example/a und https://spam.example/b",
        "http://a.example http://b.example http://c.example",
    ],
)
def test_zu_viele_links_in_anmerkung(message):
    is_spam, reason = detect_spam(honeypot_value=None, elapsed_seconds=30, message=message)
    assert is_spam is True
    assert reason == "zu_viele_links_in_anmerkung"


def test_ein_link_ist_kein_verdacht():
    is_spam, reason = detect_spam(
        honeypot_value=None, elapsed_seconds=30, message="Mehr Infos: https://planecobuilding.de"
    )
    assert is_spam is False


def test_kyrillisches_schriftsystem():
    is_spam, reason = detect_spam(honeypot_value=None, elapsed_seconds=30, message="Привет, интересует участок")
    assert is_spam is True
    assert reason == "fremdes_schriftsystem_in_anmerkung"


def test_cjk_schriftsystem():
    is_spam, reason = detect_spam(honeypot_value=None, elapsed_seconds=30, message="你好，我对这块地感兴趣")
    assert is_spam is True
    assert reason == "fremdes_schriftsystem_in_anmerkung"


def test_deutsche_umlaute_loesen_keinen_verdacht_aus():
    is_spam, reason = detect_spam(
        honeypot_value=None, elapsed_seconds=30, message="Grüße aus München, die Straße ist schön."
    )
    assert is_spam is False


def test_leere_anmerkung_ist_unproblematisch():
    is_spam, reason = detect_spam(honeypot_value=None, elapsed_seconds=30, message=None)
    assert is_spam is False
