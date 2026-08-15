"""content_hash: ein Hash über alle normalisierten Inhaltsfelder eines Leads.

Formatvarianten (Leerzeichen, Groß-/Kleinschreibung) desselben Inhalts
ergeben denselben Hash (R16), eine echte inhaltliche Änderung einen
anderen. phone_e164/email_normalized/name kommen bereits normalisiert
von den anderen core-Funktionen; Straße/Ort/Anmerkung normalisiert diese
Funktion selbst (trim, Whitespace kollabieren, kleinschreiben), da es
dafür keine eigene Funktion in diesem Block gibt.
"""
import hashlib
import json


def content_hash(
    *,
    name: str | None,
    email_normalized: str,
    phone_e164: str | None,
    street: str | None,
    postal_code: str | None,
    city: str | None,
    is_owner: bool | None,
    contact_time_preference: str | None,
    message: str | None,
    heard_about: str | None,
) -> str:
    content = {
        "name": _canonical_text(name),
        "email": email_normalized.strip().lower() if email_normalized else "",
        "phone": phone_e164 or "",
        "street": _canonical_text(street),
        "postal_code": _canonical_text(postal_code),
        "city": _canonical_text(city),
        "is_owner": is_owner,
        "contact_time_preference": _canonical_text(contact_time_preference),
        "message": _canonical_text(message),
        "heard_about": _canonical_text(heard_about),
    }
    serialized = json.dumps(content, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _canonical_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).lower()
