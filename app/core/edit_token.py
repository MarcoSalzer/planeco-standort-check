"""Signierter Korrektur-Link (Konzept §G): kein Bearbeitungs-Endpunkt, nur
Vorbefüllung. itsdangerous.URLSafeTimedSerializer über die lead_id, damit
Bestätigungsmail und Danke-Seite denselben Mechanismus benutzen statt zwei
Implementierungen zu pflegen.
"""
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "lead-edit-link"
MAX_AGE_SECONDS = 7 * 24 * 60 * 60  # 7 Tage, s. Konzept §G


def generate_edit_token(lead_id: str, secret: str) -> str:
    return URLSafeTimedSerializer(secret, salt=_SALT).dumps(lead_id)


def verify_edit_token(token: str, secret: str, max_age: int = MAX_AGE_SECONDS) -> str | None:
    """Liefert die lead_id zurück, oder None bei ungültiger/abgelaufener Signatur.

    Bewusst kein Raise: ein kaputter/abgelaufener Link soll im Formular
    still auf einen leeren Zustand zurückfallen, nicht die Seite zum
    Absturz bringen (GET / muss immer ausliefern).
    """
    try:
        return URLSafeTimedSerializer(secret, salt=_SALT).loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
