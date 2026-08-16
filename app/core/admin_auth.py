"""Admin-Login: Credential-Prüfung und Session-Token (Konzept §6, TODO Phase 3).

Reine Funktionen, Env-Credentials werden vom Aufrufer übergeben statt hier
gelesen, damit ohne Mocks testbar. Passwort-Vergleich über bcrypt.checkpw
(intern konstant in der Zeit), Username-Vergleich über hmac.compare_digest,
damit die Antwortzeit nicht verrät, ob ein Username überhaupt existiert -
beide Prüfungen laufen immer, auch wenn der Username schon nicht passt.
"""
import hmac

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "admin-session"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60  # 8 Stunden


def verify_credentials(
    username: str, password: str, *, expected_username: str, expected_password_hash: str
) -> bool:
    username_ok = hmac.compare_digest(username.encode("utf-8"), expected_username.encode("utf-8"))
    password_ok = bcrypt.checkpw(password.encode("utf-8"), expected_password_hash.encode("utf-8"))
    return username_ok and password_ok


def generate_session_token(username: str, secret: str) -> str:
    return URLSafeTimedSerializer(secret, salt=_SALT).dumps(username)


def verify_session_token(token: str, secret: str, max_age: int = SESSION_MAX_AGE_SECONDS) -> str | None:
    try:
        return URLSafeTimedSerializer(secret, salt=_SALT).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
