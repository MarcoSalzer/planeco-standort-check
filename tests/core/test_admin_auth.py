import time

import bcrypt

from app.core.admin_auth import generate_session_token, verify_credentials, verify_session_token

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
