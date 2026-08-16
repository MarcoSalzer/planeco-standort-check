"""Bestätigungsmail (Konzept §5) über Brevo HTTP-API.

Best effort, darf den Submit nie zum Scheitern bringen (CLAUDE.md Regel 2):
Timeout <=3s, jeder Fehler wird abgefangen und als Statusfeld + Event
festgehalten statt den Aufrufer zu unterbrechen. Läuft NACH dem INSERT,
auf einer eigenen Connection/Transaktion.

Reihenfolge: is_spam -> nie ("keine Mail bei Spam", Konzept §E). Sonst
Tageslimit (usage_counters, DB-geführt statt Prozessspeicher) -> DRY_RUN_EMAIL
(volle Logik, kein echter Versand) -> echter Versand über Brevo.
"""
import logging
import os
import pathlib
from datetime import datetime, timezone

import httpx
import psycopg
from jinja2 import Environment, FileSystemLoader
from psycopg.types.json import Json

from app.config import DRY_RUN_EMAIL, MAX_EMAILS_PER_DAY
from app.core.dedup import DedupCase
from app.core.display import CONTACT_TIME_LABELS
from app.core.edit_token import generate_edit_token
from app.submission import NewLeadData

logger = logging.getLogger(__name__)
dry_run_logger = logging.getLogger("app.mail.dry_run")

BREVO_TIMEOUT_SECONDS = 3.0
COUNTER_KEY_EMAIL_PER_DAY = "email_sent_day"

_TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)

_CONTACT_TIME_TEXT = {
    "vormittags": "Da Sie vormittags am besten erreichbar sind, versuchen wir es entsprechend.",
    "nachmittags": "Da Sie nachmittags am besten erreichbar sind, versuchen wir es entsprechend.",
    "abends": "Da Sie abends am besten erreichbar sind, versuchen wir es entsprechend.",
    "flexibel": "Sie haben angegeben, flexibel erreichbar zu sein — wir melden uns, sobald es passt.",
}

# Unterschiedliche Einleitung je nach Anlass (mit Marco abgestimmt, 2026-08-16).
# F1 landet nie hier (kein neuer Mailversand bei Token-Replay). F4 bekommt
# bewusst den Standardtext: aus Empfängersicht ist es eine normale neue
# Anfrage, auch wenn intern ein bekannter Kontakt erkannt wurde.
_INTRO_TEXT_DEFAULT = (
    "vielen Dank für Ihre Anfrage beim Standort-Check. Hier noch einmal Ihre "
    "Angaben zur Bestätigung:"
)
_INTRO_TEXT_BY_CASE = {
    DedupCase.F3_ERSETZT: (
        "vielen Dank für die Aktualisierung Ihrer Angaben zum Standort-Check. "
        "Wir bestätigen den Erhalt der folgenden Informationen:"
    ),
    DedupCase.F2_DUPLIKAT: (
        "vielen Dank für Ihre erneute Anfrage beim Standort-Check. Ihre Angaben "
        "entsprechen genau einer bereits bei uns vorliegenden Anfrage — es hat "
        "sich nichts geändert. Ihr Standort-Check läuft ganz normal weiter, Sie "
        "müssen nichts weiter tun:"
    ),
}


def send_confirmation_email(
    conn: psycopg.Connection, lead_id: str, data: NewLeadData, base_url: str, case: DedupCase
) -> None:
    if data.is_spam:
        # Kein Versandversuch, deshalb kein email_attempts-Zähler - reines
        # Statusfeld, das erklärt, warum nie gesendet wurde (Konzept §E).
        _update_email_status(conn, lead_id, status="uebersprungen", increment_attempts=False)
        return

    if not _reserve_daily_quota(conn):
        logger.warning("Tageslimit für Bestätigungsmails erreicht (MAX_EMAILS_PER_DAY=%s), Lead %s bleibt offen", MAX_EMAILS_PER_DAY, lead_id)
        _insert_event(conn, lead_id, "mail_fehlgeschlagen", {"grund": "tageslimit_erreicht", "max_emails_per_day": MAX_EMAILS_PER_DAY})
        return  # email_status bleibt 'offen', Retry holt es später nach

    subject, html = _render_email(data, lead_id, base_url, case)

    if DRY_RUN_EMAIL:
        dry_run_logger.info(
            "DRY_RUN_EMAIL aktiv - kein echter Versand.\nAn: %s\nBetreff: %s\n\n%s",
            data.email, subject, html,
        )
        _update_email_status(conn, lead_id, status="simuliert")
        _insert_event(conn, lead_id, "mail_gesendet", {"dry_run": True, "empfaenger": data.email})
        return

    try:
        response = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            timeout=BREVO_TIMEOUT_SECONDS,
            headers={
                "api-key": os.environ["BREVO_API_KEY"],
                "content-type": "application/json",
                "accept": "application/json",
            },
            json={
                "sender": {
                    "email": os.environ["BREVO_SENDER_EMAIL"],
                    "name": os.environ.get("BREVO_SENDER_NAME") or "Standort-Check",
                },
                "to": [{"email": data.email}],
                "subject": subject,
                "htmlContent": html,
            },
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Bestätigungsmail fehlgeschlagen für Lead %s: %s", lead_id, exc)
        _update_email_status(conn, lead_id, status="fehlgeschlagen", error=str(exc))
        _insert_event(conn, lead_id, "mail_fehlgeschlagen", {"fehler": str(exc)})
        return

    _update_email_status(conn, lead_id, status="gesendet", sent_at=datetime.now(timezone.utc))
    _insert_event(conn, lead_id, "mail_gesendet", {"empfaenger": data.email})


def _render_email(data: NewLeadData, lead_id: str, base_url: str, case: DedupCase) -> tuple[str, str]:
    edit_token = generate_edit_token(lead_id, os.environ["EDIT_TOKEN_SECRET"])
    edit_url = f"{base_url.rstrip('/')}/?k={edit_token}"

    anrede = f"Hallo {data.name}," if data.name else "Hallo,"
    intro_text = _INTRO_TEXT_BY_CASE.get(case, _INTRO_TEXT_DEFAULT)

    erwartung_text = "Unser Team meldet sich in der Regel am nächsten Werktag-Vormittag bei Ihnen."
    if data.contact_time_preference in _CONTACT_TIME_TEXT:
        erwartung_text += " " + _CONTACT_TIME_TEXT[data.contact_time_preference]

    address_parts = [data.street]
    if data.postal_code:
        address_parts.append(f"{data.postal_code} {data.city}")
    else:
        address_parts.append(data.city)
    address = ", ".join(address_parts)

    owner_text = {True: "Ja", False: "Nein"}.get(data.is_owner)
    contact_time_text = CONTACT_TIME_LABELS.get(data.contact_time_preference)

    summary_rows = [row for row in [
        ("Adresse", address),
        ("Name", data.name),
        ("E-Mail", data.email),
        ("Telefon", data.phone_raw),
        ("Eigentümer", owner_text),
        ("Erreichbarkeit", contact_time_text),
        ("Wie gefunden", data.heard_about),
        ("Anmerkung", data.message),
    ] if row[1]]

    template = _env.get_template("email_confirmation.html")
    html = template.render(
        anrede=anrede,
        intro_text=intro_text,
        summary_rows=summary_rows,
        edit_url=edit_url,
        erwartung_text=erwartung_text,
        kontakt_email=os.environ.get("KONTAKT_EMAIL") or "",
        kontakt_telefon=os.environ.get("KONTAKT_TELEFON") or "",
    )
    return "Ihre Anfrage beim Standort-Check", html


def _reserve_daily_quota(conn: psycopg.Connection) -> bool:
    window_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    row = conn.execute(
        """
        INSERT INTO usage_counters (counter_key, window_start, count)
        VALUES (%(key)s, %(window_start)s, 1)
        ON CONFLICT (counter_key, window_start)
        DO UPDATE SET count = usage_counters.count + 1, updated_at = now()
        RETURNING count
        """,
        {"key": COUNTER_KEY_EMAIL_PER_DAY, "window_start": window_start},
    ).fetchone()
    return row[0] <= MAX_EMAILS_PER_DAY


def _update_email_status(
    conn: psycopg.Connection,
    lead_id: str,
    *,
    status: str,
    sent_at: datetime | None = None,
    error: str | None = None,
    increment_attempts: bool = True,
) -> None:
    attempts_expr = "email_attempts + 1" if increment_attempts else "email_attempts"
    conn.execute(
        f"""
        UPDATE leads
        SET email_status = %(status)s,
            email_attempts = {attempts_expr},
            email_sent_at = COALESCE(%(sent_at)s, email_sent_at),
            email_last_error = %(error)s,
            updated_at = now()
        WHERE id = %(lead_id)s
        """,
        {"status": status, "sent_at": sent_at, "error": error, "lead_id": lead_id},
    )


def _insert_event(conn: psycopg.Connection, lead_id: str, event_type: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO lead_events (lead_id, event_type, payload) VALUES (%(lead_id)s, %(event_type)s, %(payload)s)",
        {"lead_id": lead_id, "event_type": event_type, "payload": Json(payload)},
    )
