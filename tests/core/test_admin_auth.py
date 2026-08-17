import time

import bcrypt

from app.core.admin_auth import (
    generate_session_token,
    verify_credentials,
    verify_retry_secret,
    verify_session_token,
)

_PASSWORD_HASH = bcrypt.hashpw(b"korrektes-passwort", bcrypt.gensalt()).decode("utf-8")


def test_richtige_credentials_werden_akzeptiert():
    assert verify_credentials(
        "anna", "korrektes-passwort", expected_username="anna", expected_password_hash=_PASSWORD_HASH
    ) is True


def test_falsches_passwort_wird_abgelehnt():
    assert verify_credentials(
        "anna", "falsches-passwort", expected_username="anna", expected_password_hash=_PASSWORD_HASH
    ) is False


def test_falscher_username_wird_abgelehnt():
    assert verify_credentials(
        "bob", "korrektes-passwort", expected_username="anna", expected_password_hash=_PASSWORD_HASH
    ) is False


def test_beides_falsch_wird_abgelehnt():
    assert verify_credentials(
        "bob", "falsch", expected_username="anna", expected_password_hash=_PASSWORD_HASH
    ) is False


def test_session_token_roundtrip():
    token = generate_session_token("anna", secret="test-secret")
    assert verify_session_token(token, secret="test-secret") == "anna"


def test_session_token_falsches_secret():
    token = generate_session_token("anna", secret="test-secret")
    assert verify_session_token(token, secret="anderes-secret") is None


def test_session_token_abgelaufen():
    token = generate_session_token("anna", secret="test-secret")
    time.sleep(2.2)
    assert verify_session_token(token, secret="test-secret", max_age=1) is None


def test_retry_secret_richtig_wird_akzeptiert():
    assert verify_retry_secret("geheim", expected="geheim") is True


def test_retry_secret_falsch_wird_abgelehnt():
    assert verify_retry_secret("falsch", expected="geheim") is False


def test_retry_secret_nichts_uebergeben_wird_abgelehnt():
    assert verify_retry_secret(None, expected="geheim") is False


def test_retry_secret_nicht_konfiguriert_wird_abgelehnt():
    # RETRY_SECRET fehlt im Environment - kein TypeError aus compare_digest,
    # sondern eindeutig "nicht autorisiert" statt eines 500ers.
    assert verify_retry_secret("irgendwas", expected=None) is False


def test_retry_secret_beides_leer_wird_abgelehnt():
    assert verify_retry_secret(None, expected=None) is False
