"""Orchestrierung des Submit-Pfads: Dedup-Kandidat suchen, entscheiden,
INSERT/UPDATE/Events schreiben. Nicht pur (DB-Zugriff) - die eigentliche
Entscheidungs-/Merge-Logik liegt in app.core.dedup / app.core.merge und
ist dort ohne DB testbar.

Ein Aufruf von persist_submission() läuft komplett auf EINER Connection,
damit alles (Token-Check, Kandidatensuche, INSERT/UPDATE, Events) in
einer Transaktion landet (psycopg3 committet beim sauberen Verlassen
des `with get_connection()`-Blocks, s. app/db.py).
"""
import dataclasses
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from app.core.dedup import DedupCase, ExistingLead, dedup_decision
from app.core.merge import merge_fields
from app.core.normalize import normalize_email, normalize_name, normalize_phone
from app.db import insert_event as _insert_event


@dataclass(frozen=True)
class NewLeadData:
    submission_token: str
    name: str | None
    name_raw: str | None
    name_normalized: bool
    email: str
    email_normalized: str
    phone_raw: str | None
    phone_e164: str | None
    phone_valid: bool
    street: str
    postal_code: str | None
    city: str
    is_owner: bool | None
    contact_time_preference: str | None
    message: str | None
    heard_about: str | None
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    utm_term: str | None
    utm_content: str | None
    gclid: str | None
    fbclid: str | None
    referrer: str | None
    landing_page: str | None
    channel: str
    channel_source: str
    content_hash: str
    is_spam: bool
    spam_reason: str | None
    privacy_accepted_at: datetime


@dataclass(frozen=True)
class SubmissionResult:
    lead_id: str
    case: DedupCase
    final_data: "NewLeadData | None"  # None nur bei F1 - kein neuer Datensatz


def persist_submission(conn: psycopg.Connection, data: NewLeadData) -> SubmissionResult:
    existing_id = _find_by_submission_token(conn, data.submission_token)
    is_replay = existing_id is not None

    # Spam-Erkennung darf bestehende Daten nie verändern (mit Marco
    # abgestimmt, 2026-08-16): bei is_spam wird gar kein Kandidat gesucht,
    # wodurch dedup_decision unten zwangsläufig auf NEU landet - keine
    # Vererbung, keine Verkettung, kein Anfassen eines Bestandsleads. Ein
    # Fehlalarm der Spam-Erkennung soll nie einen echten, bereits
    # bearbeiteten Lead als 'ersetzt' markieren können.
    candidate = None if (is_replay or data.is_spam) else _find_dedup_candidate(
        conn,
        email_normalized=data.email_normalized,
        phone_e164=data.phone_e164,
        street=data.street,
        city=data.city,
    )

    decision = dedup_decision(
        is_token_replay=is_replay,
        new_content_hash=data.content_hash,
        new_email_normalized=data.email_normalized,
        new_phone_e164=data.phone_e164,
        new_street=data.street,
        new_city=data.city,
        candidate=candidate,
    )

    if decision.case == DedupCase.F1_TECHNISCHE_DOPPLUNG:
        return SubmissionResult(lead_id=existing_id, case=decision.case, final_data=None)

    if decision.case == DedupCase.NEU:
        # data.is_spam kann hier True sein (candidate wurde dafür oben
        # bewusst auf None erzwungen, s. Kommentar dort) - der Lead bleibt
        # trotzdem ein ganz normaler eigenständiger NEU-Insert, nur mit
        # status='spam' statt 'neu'.
        status = "spam" if data.is_spam else "neu"
        new_id = _insert_lead(conn, data, duplicate_of=None, status=status, assigned_to=None, contacted_at=None)
        _insert_event(conn, new_id, "erstellt", {"quelle": "formular"})
        return SubmissionResult(lead_id=new_id, case=decision.case, final_data=data)

    if decision.case == DedupCase.F2_DUPLIKAT:
        new_id = _insert_lead(
            conn, data, duplicate_of=candidate.id, status="duplikat", assigned_to=None, contacted_at=None
        )
        _insert_event(conn, new_id, "erstellt", {"quelle": "formular"})
        _insert_event(conn, candidate.id, "erneut_angefragt", {"neuer_lead_id": new_id})
        return SubmissionResult(lead_id=new_id, case=decision.case, final_data=data)

    if decision.case == DedupCase.F3_ERSETZT:
        merged_data, changed_fields, merged_fields_ = _merge_with_candidate(data, candidate)
        new_id = _insert_lead(
            conn,
            merged_data,
            duplicate_of=None,
            status=candidate.status,
            assigned_to=candidate.assigned_to,
            contacted_at=candidate.contacted_at,
        )
        _supersede(conn, old_id=candidate.id, new_id=new_id)
        _insert_event(conn, new_id, "erstellt", {"quelle": "formular", "korrektur_von": candidate.id})
        _insert_event(
            conn,
            candidate.id,
            "ersetzt",
            {"changed_fields": changed_fields, "merged_fields": merged_fields_, "neuer_lead_id": new_id},
        )
        return SubmissionResult(lead_id=new_id, case=decision.case, final_data=merged_data)

    if decision.case == DedupCase.F4_KONTAKT_BEKANNT:
        new_id = _insert_lead(conn, data, duplicate_of=None, status="neu", assigned_to=None, contacted_at=None)
        _insert_event(conn, new_id, "erstellt", {"quelle": "formular"})
        _insert_event(conn, new_id, "kontakt_bekannt", {"bekannter_lead_id": candidate.id})
        return SubmissionResult(lead_id=new_id, case=decision.case, final_data=data)

    raise ValueError(f"Unbekannter DedupCase: {decision.case}")  # pragma: no cover


def resolve_current_lead(conn: psycopg.Connection, lead_id: str) -> dict | None:
    """Folgt der superseded_by-Kette zur aktuell führenden Version eines Leads.

    Für die Vorbefüllung über den signierten Korrektur-Link (Konzept §G):
    ein Token kann auf einen Lead zeigen, der inzwischen durch eine
    Korrektur ersetzt wurde - dann soll der AKTUELLE Stand vorbefüllt
    werden, nicht der veraltete.
    """
    current_id = lead_id
    with conn.cursor(row_factory=dict_row) as cur:
        for _ in range(50):  # Sicherheitsnetz gegen einen (eigentlich unmöglichen) Zyklus
            cur.execute(
                """
                SELECT id, street, postal_code, city, email, phone_raw, name_raw,
                       is_owner, contact_time_preference, message, heard_about, superseded_by
                FROM leads WHERE id = %(id)s
                """,
                {"id": current_id},
            )
            row = cur.fetchone()
            if row is None:
                return None
            if row["superseded_by"] is None:
                return row
            current_id = row["superseded_by"]
    return None


def _merge_with_candidate(
    data: NewLeadData, candidate: ExistingLead
) -> tuple[NewLeadData, dict, dict]:
    old_content = {
        "name_raw": candidate.name_raw,
        "email": candidate.email,
        "phone_raw": candidate.phone_raw,
        "street": candidate.street,
        "postal_code": candidate.postal_code,
        "city": candidate.city,
        "is_owner": candidate.is_owner,
        "contact_time_preference": candidate.contact_time_preference,
        "message": candidate.message,
        "heard_about": candidate.heard_about,
    }
    new_content = {
        "name_raw": data.name_raw,
        "email": data.email,
        "phone_raw": data.phone_raw,
        "street": data.street,
        "postal_code": data.postal_code,
        "city": data.city,
        "is_owner": data.is_owner,
        "contact_time_preference": data.contact_time_preference,
        "message": data.message,
        "heard_about": data.heard_about,
    }
    merge_result = merge_fields(old=old_content, new=new_content)
    v = merge_result.values

    merged_name, merged_name_normalized = normalize_name(v["name_raw"])
    merged_email_normalized = normalize_email(v["email"])
    merged_phone_e164, merged_phone_valid = normalize_phone(v["phone_raw"])

    from app.core.content_hash import content_hash as compute_content_hash

    merged_content_hash = compute_content_hash(
        name=merged_name,
        email_normalized=merged_email_normalized,
        phone_e164=merged_phone_e164,
        street=v["street"],
        postal_code=v["postal_code"],
        city=v["city"],
        is_owner=v["is_owner"],
        contact_time_preference=v["contact_time_preference"],
        message=v["message"],
        heard_about=v["heard_about"],
    )

    merged_data = dataclasses.replace(
        data,
        name=merged_name,
        name_raw=v["name_raw"],
        name_normalized=merged_name_normalized,
        email=v["email"],
        email_normalized=merged_email_normalized,
        phone_raw=v["phone_raw"],
        phone_e164=merged_phone_e164,
        phone_valid=merged_phone_valid,
        street=v["street"],
        postal_code=v["postal_code"],
        city=v["city"],
        is_owner=v["is_owner"],
        contact_time_preference=v["contact_time_preference"],
        message=v["message"],
        heard_about=v["heard_about"],
        content_hash=merged_content_hash,
    )
    return merged_data, merge_result.changed_fields, merge_result.merged_fields


def _find_by_submission_token(conn: psycopg.Connection, submission_token: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM leads WHERE submission_token = %(token)s", {"token": submission_token}
    ).fetchone()
    return str(row[0]) if row else None


def _find_dedup_candidate(
    conn: psycopg.Connection,
    *,
    email_normalized: str,
    phone_e164: str | None,
    street: str,
    city: str,
) -> ExistingLead | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, content_hash, email, email_normalized, phone_raw, phone_e164,
                   street, postal_code, city, name_raw, is_owner, contact_time_preference,
                   message, heard_about, status, assigned_to, contacted_at
            FROM leads
            WHERE status NOT IN ('duplikat', 'ersetzt', 'spam')
              AND (
                phone_e164 = %(phone_e164)s
                OR email_normalized = %(email_normalized)s
                OR (lower(trim(street)) = %(street_norm)s AND lower(trim(city)) = %(city_norm)s)
              )
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {
                "phone_e164": phone_e164,
                "email_normalized": email_normalized,
                "street_norm": street.strip().lower(),
                "city_norm": city.strip().lower(),
            },
        )
        row = cur.fetchone()
    if row is None:
        return None
    return ExistingLead(id=str(row["id"]), **{k: v for k, v in row.items() if k != "id"})


def _insert_lead(
    conn: psycopg.Connection,
    data: NewLeadData,
    *,
    duplicate_of: str | None,
    status: str,
    assigned_to: str | None,
    contacted_at: datetime | None,
) -> str:
    row = conn.execute(
        """
        INSERT INTO leads (
            submission_token, name, name_raw, name_normalized,
            email, email_normalized, phone_raw, phone_e164, phone_valid,
            street, postal_code, city,
            is_owner, contact_time_preference, message, heard_about,
            utm_source, utm_medium, utm_campaign, utm_term, utm_content,
            gclid, fbclid, referrer, landing_page,
            channel, channel_source, content_hash, duplicate_of,
            status, assigned_to, contacted_at,
            is_spam, spam_reason, privacy_accepted_at
        ) VALUES (
            %(submission_token)s, %(name)s, %(name_raw)s, %(name_normalized)s,
            %(email)s, %(email_normalized)s, %(phone_raw)s, %(phone_e164)s, %(phone_valid)s,
            %(street)s, %(postal_code)s, %(city)s,
            %(is_owner)s, %(contact_time_preference)s, %(message)s, %(heard_about)s,
            %(utm_source)s, %(utm_medium)s, %(utm_campaign)s, %(utm_term)s, %(utm_content)s,
            %(gclid)s, %(fbclid)s, %(referrer)s, %(landing_page)s,
            %(channel)s, %(channel_source)s, %(content_hash)s, %(duplicate_of)s,
            %(status)s, %(assigned_to)s, %(contacted_at)s,
            %(is_spam)s, %(spam_reason)s, %(privacy_accepted_at)s
        )
        RETURNING id
        """,
        {
            **dataclasses.asdict(data),
            "duplicate_of": duplicate_of,
            "status": status,
            "assigned_to": assigned_to,
            "contacted_at": contacted_at,
        },
    ).fetchone()
    return str(row[0])


def _supersede(conn: psycopg.Connection, *, old_id: str, new_id: str) -> None:
    conn.execute(
        "UPDATE leads SET status = 'ersetzt', superseded_by = %(new_id)s, updated_at = now() "
        "WHERE id = %(old_id)s",
        {"new_id": new_id, "old_id": old_id},
    )
