import time

from app.core.edit_token import generate_edit_token, verify_edit_token


def test_generate_und_verify_roundtrip():
    token = generate_edit_token("lead-123", secret="test-secret")
    assert verify_edit_token(token, secret="test-secret") == "lead-123"


def test_falsches_secret_wird_abgelehnt():
    token = generate_edit_token("lead-123", secret="test-secret")
    assert verify_edit_token(token, secret="anderes-secret") is None


def test_manipulierter_token_wird_abgelehnt():
    # Zeichen in der Mitte kippen, nicht das letzte: das letzte Zeichen einer
    # base64-kodierten Signatur kann "Slack-Bits" ohne Informationsgehalt
    # haben, wodurch ein Flip dort manchmal denselben Wert dekodiert
    # (beobachtete Flakiness bei token[-1]).
    token = generate_edit_token("lead-123", secret="test-secret")
    mid = len(token) // 2
    manipuliert = token[:mid] + ("a" if token[mid] != "a" else "b") + token[mid + 1:]
    assert verify_edit_token(manipuliert, secret="test-secret") is None


def test_abgelaufener_token_wird_abgelehnt():
    token = generate_edit_token("lead-123", secret="test-secret")
    time.sleep(2.2)
    assert verify_edit_token(token, secret="test-secret", max_age=1) is None


def test_voellig_kaputter_token_crasht_nicht():
    assert verify_edit_token("das-ist-kein-token", secret="test-secret") is None
