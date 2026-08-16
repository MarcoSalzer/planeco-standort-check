"""validate_submission: serverseitige Pflichtfeld- und Formatprüfung.

Konzept §3.1 (Pflichtfelder) + §D/§K (E-Mail-Syntax). Clientseitige
Prüfungen sind Komfort, nie Sicherheit (CLAUDE.md Regel 11) - ein
direkter POST muss dieselben Prüfungen durchlaufen wie das Formular.

Bewusst NICHT Teil dieser Funktion: die MX-Record-Prüfung aus Konzept
§D (email-validator mit check_deliverability=True). Das ist ein
Netzwerk-Aufruf während der Validierung und damit ein eigener, größerer
Baustein als reine Syntaxprüfung - hier nur die lokale Syntaxprüfung
ohne DNS-Zugriff, damit diese Funktion ohne Netzwerk testbar bleibt.
"""
import re

from email_validator import EmailNotValidError, validate_email

_POSTAL_CODE_RE = re.compile(r"\d{5}")
_CONTACT_TIME_PREFERENCES = {"vormittags", "nachmittags", "flexibel"}


def validate_submission(
    *,
    street: str | None,
    city: str | None,
    email: str | None,
    postal_code: str | None,
    contact_time_preference: str | None,
    privacy_accepted: bool,
) -> dict[str, str]:
    errors: dict[str, str] = {}

    if not _filled(street):
        errors["street"] = "Bitte Straße und Hausnummer angeben."
    if not _filled(city):
        errors["city"] = "Bitte Ort angeben."

    if not _filled(email):
        errors["email"] = "Bitte E-Mail-Adresse angeben."
    else:
        try:
            validate_email(email.strip(), check_deliverability=False)
        except EmailNotValidError:
            errors["email"] = "Bitte eine gültige E-Mail-Adresse angeben."

    if postal_code and postal_code.strip() and not _POSTAL_CODE_RE.fullmatch(postal_code.strip()):
        errors["postal_code"] = "PLZ muss 5-stellig sein."

    if contact_time_preference and contact_time_preference not in _CONTACT_TIME_PREFERENCES:
        errors["contact_time_preference"] = "Ungültige Auswahl."

    if not privacy_accepted:
        errors["privacy_accepted"] = "Bitte Datenschutzerklärung akzeptieren."

    return errors


def _filled(value: str | None) -> bool:
    return value is not None and value.strip() != ""
