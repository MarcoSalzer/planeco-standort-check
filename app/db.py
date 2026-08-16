import os

import psycopg
from psycopg.types.json import Json


def get_connection() -> psycopg.Connection:
    """Öffnet eine neue DB-Connection für einen einzelnen Request.

    Kein globaler Pool im Modulzustand (Serverless-Instanzen werden ohne
    Vorwarnung beendet). prepare_threshold=None, weil der Supabase
    Transaction Pooler (Port 6543) keine Prepared Statements unterstützt.
    """
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL ist nicht gesetzt.")
    return psycopg.connect(dsn, prepare_threshold=None)


def insert_event(conn: psycopg.Connection, lead_id: str, event_type: str, payload: dict) -> None:
    """Append-only Schreibhilfe für lead_events (Konzept §2).

    War als private _insert_event() in app/submission.py UND app/mail.py
    identisch dupliziert; mit app/admin.py als drittem Aufrufer (Aktionen)
    hierher konsolidiert.
    """
    conn.execute(
        "INSERT INTO lead_events (lead_id, event_type, payload) VALUES (%(lead_id)s, %(event_type)s, %(payload)s)",
        {"lead_id": lead_id, "event_type": event_type, "payload": Json(payload)},
    )
