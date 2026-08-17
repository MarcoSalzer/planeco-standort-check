"""Retry-Orchestrierung für POST /admin/retry (Konzept §1/§G, TODO Phase 4
Block b): arbeitet Leads ab, deren Geocoding oder Bestätigungsmail beim
Submit offen blieb oder scheiterte.

Trigger laut Konzept §1: Dashboard-Button UND GitHub-Actions-Cron alle
15 min (app/admin.py prüft Session-Cookie ODER RETRY_SECRET-Header, s.
app/core/admin_auth.py::verify_retry_secret).

Nicht pur (DB-/HTTP-Zugriff über app/geocoding.py und app/mail.py) - wie
diese beiden Module bewusst ohne automatisierte Tests (CLAUDE.md Regel 5
gilt nur für app/core/*), stattdessen live gegen echte Nominatim-/Brevo-
Aufrufe verifiziert (wie Phase 4 Block a).

Jeder Lead läuft auf einer EIGENEN Connection (wie main.py::submit für
Mail/Geocoding), damit ein Fehler bei Lead N nicht bereits committete
Ergebnisse von Lead 1..N-1 zurückrollt.
"""
import dataclasses
import logging
import time
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.config import DRY_RUN_GEOCODE, GEOCODE_BATCH_SIZE, MAX_GEOCODE_PER_MINUTE
from app.core.dedup import DedupCase
from app.core.geocoding import GeocodeResult
from app.db import get_connection, insert_event
from app.geocoding import geocode
from app.mail import send_auslandshinweis_email, send_confirmation_email
from app.submission import NewLeadData, row_to_new_lead_data
from app.traffic_light import apply_traffic_light

logger = logging.getLogger(__name__)
dry_run_logger = logging.getLogger("app.retry.dry_run")

COUNTER_KEY_GEOCODE_PER_MINUTE = "geocode_minute"
# Nominatim-Nutzungsbedingungen: max. 1 Anfrage/Sekunde. >1.0 als
# Sicherheitsspanne (Uhr-/Netzwerk-Jitter), s. auch die manuelle
# Live-Verifikation in Phase 4 Block a (dort 1.2-1.5s verwendet).
NOMINATIM_MIN_INTERVAL_SECONDS = 1.1

# Nur diese beiden gelten als "noch nicht abgearbeitet" (CLAUDE.md: "Der
# Retry-Endpunkt filtert immer auf process_after <= now()" - für BEIDE
# Nebenwirkungen, nicht nur Geocoding, s. auch app/submission.py).
_GEOCODE_RETRY_STATUSES = ["offen", "fehlgeschlagen"]
_EMAIL_RETRY_STATUSES = ["offen", "fehlgeschlagen"]

# Kein Ratenlimit wie bei Nominatim (Brevo hat keine 1/s-Regel, MAX_EMAILS_
# PER_DAY sichert das Tageskontingent bereits pro Aufruf ab), aber dieselbe
# Portions-Idee wie GEOCODE_BATCH_SIZE: eine feste, kleine Obergrenze
# reicht, weil fehlgeschlagene Mails in der Praxis selten sind (nur
# Tageslimit oder ein echter Brevo-Ausfall) - kein eigenes Env nötig.
_MAIL_RETRY_BATCH_SIZE = 10


def run_retry(*, base_url: str) -> dict:
    return {
        "geocoding": _retry_geocoding(),
        "mail": _retry_mail(base_url=base_url),
        "auslandshinweis": _retry_auslandshinweis(),
    }


def retry_one_geocode(lead_id: str) -> str:
    """Für den Button "Geocoding wiederholen" bei einem einzelnen Lead
    (Block d) - anders als der Batch-Lauf IMMER versucht, unabhängig vom
    aktuellen geocode_status (eine bewusste manuelle Wiederholung, kein
    automatischer Sweep über noch offene Fälle). Respektiert trotzdem
    MAX_GEOCODE_PER_MINUTE/DRY_RUN_GEOCODE wie der Batch-Lauf - Nominatims
    Limit gilt unabhängig vom Auslöser. Gibt "ratenlimit" statt None
    zurück, wenn das Kontingent für diese Minute erschöpft ist - der
    Aufrufer (Admin-Route) braucht einen anzeigbaren String, kein
    Abbruchsignal für eine Schleife wie im Batch-Fall."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, street, postal_code, city FROM leads WHERE id = %(id)s",
            {"id": lead_id},
        ).fetchone()
    if row is None:
        raise ValueError(f"Lead {lead_id} nicht gefunden.")
    lead = {"id": row[0], "street": row[1], "postal_code": row[2], "city": row[3]}
    status = _process_one_geocode(lead)
    return status if status is not None else "ratenlimit"


# --- Geocoding ---------------------------------------------------------


def _retry_geocoding() -> dict:
    with get_connection() as conn:
        candidates = _fetch_geocode_candidates(conn, limit=GEOCODE_BATCH_SIZE)

    nach_status: dict[str, int] = {}
    verarbeitet = 0
    for i, lead in enumerate(candidates):
        if i > 0:
            time.sleep(NOMINATIM_MIN_INTERVAL_SECONDS)
        status = _process_one_geocode(lead)
        if status is None:
            # Kontingent (MAX_GEOCODE_PER_MINUTE) erschöpft - nichts
            # geschrieben, Rest bleibt für den nächsten Lauf liegen statt
            # weiter gegen ein leeres Kontingent zu laufen.
            logger.warning(
                "MAX_GEOCODE_PER_MINUTE erreicht nach %s von %s Kandidaten - Rest folgt beim nächsten Aufruf",
                verarbeitet, len(candidates),
            )
            break
        nach_status[status] = nach_status.get(status, 0) + 1
        verarbeitet += 1

    with get_connection() as conn:
        verbleibend = _count_geocode_candidates(conn)

    return {"verarbeitet": verarbeitet, "nach_status": nach_status, "verbleibend": verbleibend}


def _fetch_geocode_candidates(conn: psycopg.Connection, *, limit: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, street, postal_code, city
            FROM leads
            WHERE geocode_status = ANY(%(statuses)s) AND process_after <= now()
            ORDER BY process_after ASC
            LIMIT %(limit)s
            """,
            {"statuses": _GEOCODE_RETRY_STATUSES, "limit": limit},
        )
        return cur.fetchall()


def _count_geocode_candidates(conn: psycopg.Connection) -> int:
    row = conn.execute(
        "SELECT count(*) FROM leads WHERE geocode_status = ANY(%(statuses)s) AND process_after <= now()",
        {"statuses": _GEOCODE_RETRY_STATUSES},
    ).fetchone()
    return row[0]


def _process_one_geocode(lead: dict) -> str | None:
    """None: Kontingent erschöpft, nichts geschrieben. Sonst der
    resultierende geocode_status."""
    lead_id = str(lead["id"])
    try:
        with get_connection() as conn:
            # Reihenfolge wie app/mail.py (_reserve_daily_quota VOR
            # DRY_RUN_EMAIL): der Zähler wird auch im Dry-Run konsumiert,
            # damit ein Dry-Run den vollen Ablauf inkl. Kontingent-Prüfung
            # testet, nicht nur den Erfolgsfall.
            if not _reserve_geocode_quota(conn):
                return None
            if DRY_RUN_GEOCODE:
                return _simulate_geocode(conn, lead_id, lead)
            result = geocode(street=lead["street"], postal_code=lead["postal_code"], city=lead["city"])
            _apply_geocode_result(conn, lead_id, result)
            return result.status
    except Exception:
        logger.exception("Geocoding-Retry fehlgeschlagen für Lead %s", lead_id)
        with get_connection() as conn:
            _mark_geocode_failed(conn, lead_id, error="unerwarteter Fehler beim Retry")
        return "fehlgeschlagen"


def _reserve_geocode_quota(conn: psycopg.Connection) -> bool:
    window_start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    row = conn.execute(
        """
        INSERT INTO usage_counters (counter_key, window_start, count)
        VALUES (%(key)s, %(window_start)s, 1)
        ON CONFLICT (counter_key, window_start)
        DO UPDATE SET count = usage_counters.count + 1, updated_at = now()
        RETURNING count
        """,
        {"key": COUNTER_KEY_GEOCODE_PER_MINUTE, "window_start": window_start},
    ).fetchone()
    return row[0] <= MAX_GEOCODE_PER_MINUTE


def _simulate_geocode(conn: psycopg.Connection, lead_id: str, lead: dict) -> str:
    dry_run_logger.info(
        "DRY_RUN_GEOCODE aktiv - kein echter Nominatim-Aufruf.\nStraße: %s\nPLZ: %s\nOrt: %s",
        lead["street"], lead["postal_code"], lead["city"],
    )
    conn.execute(
        """
        UPDATE leads SET geocode_status = 'simuliert', geocode_attempts = geocode_attempts + 1,
               updated_at = now()
        WHERE id = %(id)s
        """,
        {"id": lead_id},
    )
    insert_event(conn, lead_id, "geocodiert", {"status": "simuliert", "dry_run": True})
    apply_traffic_light(conn, lead_id)  # Block c: nach jeder geocode_status-Änderung
    return "simuliert"


def _apply_geocode_result(conn: psycopg.Connection, lead_id: str, result: GeocodeResult) -> None:
    conn.execute(
        """
        UPDATE leads
        SET geocode_status = %(status)s,
            geocode_attempts = geocode_attempts + 1,
            lat = %(lat)s, lon = %(lon)s,
            geo_municipality = %(geo_municipality)s, geo_state = %(geo_state)s,
            geo_country = %(geo_country)s, geocode_raw = %(geocode_raw)s,
            in_service_area = %(in_service_area)s,
            geo_state_unresolved = %(geo_state_unresolved)s,
            geocode_candidate_count = %(candidate_count)s,
            updated_at = now()
        WHERE id = %(lead_id)s
        """,
        {
            "status": result.status,
            "lat": result.lat, "lon": result.lon,
            "geo_municipality": result.geo_municipality, "geo_state": result.geo_state,
            "geo_country": result.geo_country,
            "geocode_raw": Json(result.raw) if result.raw is not None else None,
            "in_service_area": result.in_service_area,
            "geo_state_unresolved": result.geo_state_unresolved,
            "candidate_count": result.candidate_count,
            "lead_id": lead_id,
        },
    )
    insert_event(
        conn, lead_id, "geocodiert",
        {"status": result.status, "candidate_count": result.candidate_count, "ort": result.geo_municipality},
    )
    if result.in_service_area is False:
        _flag_as_ausland(conn, lead_id)
    apply_traffic_light(conn, lead_id)  # Block c: nach jeder geocode_status-Änderung


def _flag_as_ausland(conn: psycopg.Connection, lead_id: str) -> None:
    """Konzept §A: Adresse eindeutig außerhalb Deutschlands -> eigener
    Status 'ausland' (eigener Dashboard-Filter, aber nicht verloren) +
    ausland_hinweis_status startet bei 'offen', damit _retry_auslandshinweis()
    unten die zweite Mail aufgreift.

    Nur beim ERSTEN Übergang etwas ändern: Block d erlaubt, das Geocoding
    eines einzelnen Leads jederzeit manuell zu wiederholen, unabhängig vom
    aktuellen Status - kommt dabei für einen bereits als 'ausland' erkannten
    Lead wieder in_service_area=false heraus, darf das keine zweite Mail
    und kein zweites status_geaendert-Event auslösen. status_vorher wird
    dafür vorab gelesen (kein RETURNING-Trick, weil zwei unabhängig
    voneinander bedingte Spalten aktualisiert werden)."""
    row = conn.execute(
        "SELECT status, ausland_hinweis_status FROM leads WHERE id = %(id)s", {"id": lead_id}
    ).fetchone()
    status_vorher, ausland_status_vorher = row[0], row[1]

    updates: dict = {}
    if status_vorher != "ausland":
        updates["status"] = "ausland"
    if ausland_status_vorher == "nicht_noetig":
        updates["ausland_hinweis_status"] = "offen"

    if not updates:
        return

    set_clauses = ", ".join(f"{column} = %({column})s" for column in updates)
    conn.execute(
        f"UPDATE leads SET {set_clauses}, updated_at = now() WHERE id = %(lead_id)s",
        {**updates, "lead_id": lead_id},
    )
    if "status" in updates:
        insert_event(conn, lead_id, "status_geaendert", {"von": status_vorher, "nach": "ausland", "grund": "geocoding"})


def _mark_geocode_failed(conn: psycopg.Connection, lead_id: str, *, error: str) -> None:
    conn.execute(
        """
        UPDATE leads SET geocode_status = 'fehlgeschlagen', geocode_attempts = geocode_attempts + 1,
               updated_at = now()
        WHERE id = %(id)s
        """,
        {"id": lead_id},
    )
    insert_event(conn, lead_id, "geocodiert", {"status": "fehlgeschlagen", "fehler": error})
    apply_traffic_light(conn, lead_id)  # Block c: nach jeder geocode_status-Änderung


# --- Mail ----------------------------------------------------------------


def _retry_mail(*, base_url: str) -> dict:
    with get_connection() as conn:
        candidates = _fetch_mail_candidates(conn, limit=_MAIL_RETRY_BATCH_SIZE)

    nach_status: dict[str, int] = {}
    for lead in candidates:
        status = _process_one_mail(lead, base_url=base_url)
        nach_status[status] = nach_status.get(status, 0) + 1

    with get_connection() as conn:
        verbleibend = _count_mail_candidates(conn)

    return {"verarbeitet": len(candidates), "nach_status": nach_status, "verbleibend": verbleibend}


def _fetch_mail_candidates(conn: psycopg.Connection, *, limit: int) -> list[dict]:
    columns = ", ".join(f.name for f in dataclasses.fields(NewLeadData))
    # columns kommt ausschließlich aus den fest im Code stehenden
    # NewLeadData-Feldnamen, nie aus einer Anfrage - sicher trotz
    # f-String-Interpolation (dasselbe Muster wie app/admin.py).
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, {columns}
            FROM leads
            WHERE email_status = ANY(%(statuses)s) AND process_after <= now()
            ORDER BY process_after ASC
            LIMIT %(limit)s
            """,
            {"statuses": _EMAIL_RETRY_STATUSES, "limit": limit},
        )
        return cur.fetchall()


def _count_mail_candidates(conn: psycopg.Connection) -> int:
    row = conn.execute(
        "SELECT count(*) FROM leads WHERE email_status = ANY(%(statuses)s) AND process_after <= now()",
        {"statuses": _EMAIL_RETRY_STATUSES},
    ).fetchone()
    return row[0]


def _process_one_mail(lead: dict, *, base_url: str) -> str:
    lead_id = str(lead["id"])
    data = row_to_new_lead_data(lead)
    try:
        with get_connection() as conn:
            # DedupCase.NEU wie beim manuellen Resend (app/admin.py) - der
            # ursprüngliche Fall (NEU/F2/F3/F4) ließe sich nur über einen
            # zusätzlichen Rückwärts-Lookup rekonstruieren; er beeinflusst
            # nur die Einleitung der Mail, nicht deren fachlichen Inhalt.
            return send_confirmation_email(conn, lead_id, data, base_url, DedupCase.NEU)
    except Exception:
        logger.exception("Mail-Retry fehlgeschlagen für Lead %s", lead_id)
        return "fehler_unerwartet"


# --- Auslandshinweis (Konzept §A) ------------------------------------------
# Läuft "über denselben Retry-Pfad" wie die Bestätigungsmail (§A) - eigener
# Zweig statt in _retry_mail() mitzulaufen, weil beide Mails unabhängig
# voneinander scheitern/erneut versucht werden können (eigene Statusspalte
# ausland_hinweis_status statt email_status) und eine gemeinsame Funktion
# beide Fälle stärker verzahnt hätte, als der Konzept-Text nahelegt.

_AUSLANDSHINWEIS_RETRY_STATUSES = ["offen", "fehlgeschlagen"]
# Kein eigenes Env wie bei _MAIL_RETRY_BATCH_SIZE nötig - Auslandsfälle sind
# in der Praxis selten (Konzept: bundesweites Angebot, Auslandsadressen sind
# der Ausnahmefall), dieselbe kleine, feste Obergrenze reicht.
_AUSLANDSHINWEIS_RETRY_BATCH_SIZE = 10


def _retry_auslandshinweis() -> dict:
    with get_connection() as conn:
        candidates = _fetch_auslandshinweis_candidates(conn, limit=_AUSLANDSHINWEIS_RETRY_BATCH_SIZE)

    nach_status: dict[str, int] = {}
    for lead in candidates:
        status = _process_one_auslandshinweis(lead)
        nach_status[status] = nach_status.get(status, 0) + 1

    with get_connection() as conn:
        verbleibend = _count_auslandshinweis_candidates(conn)

    return {"verarbeitet": len(candidates), "nach_status": nach_status, "verbleibend": verbleibend}


def _fetch_auslandshinweis_candidates(conn: psycopg.Connection, *, limit: int) -> list[dict]:
    columns = ", ".join(f.name for f in dataclasses.fields(NewLeadData))
    # columns kommt ausschließlich aus den fest im Code stehenden
    # NewLeadData-Feldnamen (wie _fetch_mail_candidates oben) - sicher trotz
    # f-String-Interpolation.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT id, {columns}
            FROM leads
            WHERE ausland_hinweis_status = ANY(%(statuses)s) AND process_after <= now()
            ORDER BY process_after ASC
            LIMIT %(limit)s
            """,
            {"statuses": _AUSLANDSHINWEIS_RETRY_STATUSES, "limit": limit},
        )
        return cur.fetchall()


def _count_auslandshinweis_candidates(conn: psycopg.Connection) -> int:
    row = conn.execute(
        "SELECT count(*) FROM leads WHERE ausland_hinweis_status = ANY(%(statuses)s) AND process_after <= now()",
        {"statuses": _AUSLANDSHINWEIS_RETRY_STATUSES},
    ).fetchone()
    return row[0]


def _process_one_auslandshinweis(lead: dict) -> str:
    lead_id = str(lead["id"])
    data = row_to_new_lead_data(lead)
    try:
        with get_connection() as conn:
            return send_auslandshinweis_email(conn, lead_id, data)
    except Exception:
        logger.exception("Auslandshinweis-Retry fehlgeschlagen für Lead %s", lead_id)
        return "fehler_unerwartet"
