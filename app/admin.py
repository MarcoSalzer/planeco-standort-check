"""Admin-Dashboard: Login + Lead-Liste + Detailansicht + Aktionen + CSV-
Export + Auswertung (Konzept §6/§7). Damit ist Phase 3 vollständig.

Session per signiertem Cookie (itsdangerous, SESSION_SECRET - eigenes
Secret, getrennt von EDIT_TOKEN_SECRET, s. app/core/admin_auth.py).
"""
import csv
import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import psycopg
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from psycopg.rows import dict_row

from app.core.admin_auth import (
    SESSION_MAX_AGE_SECONDS,
    generate_session_token,
    verify_credentials,
    verify_retry_secret,
    verify_session_token,
)
from app.core.ampel import ampel as compute_ampel
from app.core.channel import CHANNEL_LABELS
from app.core.dedup import DedupCase
from app.core.display import (
    CONTACT_TIME_LABELS,
    EVENT_TYPE_LABELS,
    berlin_today_iso,
    format_berlin_datetime,
    format_duration_de,
    status_label,
)
from app.core.spam import SPAM_REASON_LABELS
from app.db import get_connection, insert_event
from app.mail import send_confirmation_email
from app.retry import run_retry
from app.submission import NewLeadData, row_to_new_lead_data
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

SESSION_COOKIE_NAME = "standort_check_admin_session"

# Tabs -> welche status-Werte sie zeigen. 'alle' filtert nicht nach Status,
# unterliegt aber (wie die anderen drei auch) dem _HIDDEN_STATUSES-Toggle.
_TAB_STATUSES: dict[str, list[str] | None] = {
    "neu": ["neu"],
    "bearbeitung": ["kontaktiert"],
    "erledigt": ["qualifiziert", "disqualifiziert"],
    "alle": None,
}
_TAB_LABELS: dict[str, str] = {
    "neu": "Neu",
    "bearbeitung": "In Bearbeitung",
    "erledigt": "Erledigt",
    "alle": "Alle",
}
_DEFAULT_TAB = "neu"

# Sortierung: Neu/Bearbeitung sind eine Warteschlange (älteste zuerst
# abarbeiten), Erledigt/Alle sind Nachschlagewerke (neueste zuerst - man
# sucht meist die letzte Aktivität). Per ?sort=aeltest|neueste explizit
# umschaltbar; ohne den Parameter gilt der Tab-Default (Marco, 2026-08-16).
_TAB_DEFAULT_SORT_OLDEST_FIRST = {
    "neu": True,
    "bearbeitung": True,
    "erledigt": False,
    "alle": False,
}

# duplicate/superseded/spam/ausland: nicht Teil der normalen Sales-Warte-
# schlange (Konzept §4, §A), default ausgeblendet, Toggle "alles anzeigen".
_HIDDEN_STATUSES = ["duplikat", "ersetzt", "spam", "ausland"]

# Feste Optionslisten für die zwei Dropdown-Filter über der Liste (Marco,
# 2026-08-16: "nur diese beiden, keine Filter pro Spalte"). Fest statt per
# DISTINCT-Query aus der DB abgeleitet, damit der Filter schon vor Phase 4
# vollständig nutzbar ist (aktuell hat kein Lead ein geo_state, die Liste
# wäre sonst leer) und damit "kommt aktuell nicht vor" nicht mit "gibt es
# nicht" verwechselt wird.
_BUNDESLAENDER = [
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg",
    "Hessen", "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen",
    "Rheinland-Pfalz", "Saarland", "Sachsen", "Sachsen-Anhalt",
    "Schleswig-Holstein", "Thüringen",
]

# Per Hand im Dashboard setzbare status-Werte (Aktionen, Konzept §6).
# 'duplikat'/'ersetzt'/'ausland' bewusst NICHT dabei: die entstehen nur
# zusammen mit einer echten Relation (duplicate_of/superseded_by bzw.
# Geocoding-Ergebnis) - ein Dropdown könnte diese Relation nicht mitsetzen
# und würde einen Datensatz erzeugen, der wie 'ersetzt' aussieht, ohne
# einen Nachfolger zu haben. 'spam' ist bewusst dabei: Konzept §J verlangt
# ausdrücklich, dass ein Fehlalarm "manuell freigegeben werden kann" - und
# symmetrisch dazu muss auch ein übersehener Spam-Fall manuell markierbar
# sein.
_MANUALLY_SETTABLE_STATUSES = ["neu", "kontaktiert", "qualifiziert", "disqualifiziert", "spam"]


def _current_admin(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        logger.warning("SESSION_SECRET nicht gesetzt - Admin-Session kann nicht geprüft werden")
        return None
    return verify_session_token(token, secret)


@router.get("/login")
def login_form(request: Request):
    if _current_admin(request):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(request=request, name="admin_login.html", context={"error": None})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    admin_user = os.environ.get("ADMIN_USER")
    admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    session_secret = os.environ.get("SESSION_SECRET")

    if not admin_user or not admin_password_hash or not session_secret:
        logger.warning("ADMIN_USER/ADMIN_PASSWORD_HASH/SESSION_SECRET nicht vollständig gesetzt")
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={"error": "Login ist derzeit nicht konfiguriert."},
            status_code=503,
        )

    ok = verify_credentials(
        username, password, expected_username=admin_user, expected_password_hash=admin_password_hash
    )
    if not ok:
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={"error": "Benutzername oder Passwort falsch."},
            status_code=401,
        )

    token = generate_session_token(username, session_secret)
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


def _resolve_dashboard_params(request: Request) -> dict:
    tab = request.query_params.get("tab", _DEFAULT_TAB)
    if tab not in _TAB_STATUSES:
        tab = _DEFAULT_TAB

    sort_param = request.query_params.get("sort")
    if sort_param == "neueste":
        sort_oldest_first, sort_explicit = False, "neueste"
    elif sort_param == "aeltest":
        sort_oldest_first, sort_explicit = True, "aeltest"
    else:
        # Kein expliziter Wunsch -> Tab-Default, s. _TAB_DEFAULT_SORT_OLDEST_FIRST.
        sort_oldest_first, sort_explicit = _TAB_DEFAULT_SORT_OLDEST_FIRST.get(tab, True), None

    channel_filter = request.query_params.get("channel") or None
    if channel_filter not in CHANNEL_LABELS:
        channel_filter = None
    bundesland_filter = request.query_params.get("bundesland") or None
    if bundesland_filter not in _BUNDESLAENDER:
        bundesland_filter = None

    return {
        "tab": tab,
        "show_all": request.query_params.get("alle") == "1",
        "search": (request.query_params.get("q") or "").strip() or None,
        "sort_oldest_first": sort_oldest_first,
        "sort_explicit": sort_explicit,
        "channel_filter": channel_filter,
        "bundesland_filter": bundesland_filter,
    }


@router.get("")
def dashboard(request: Request):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    p = _resolve_dashboard_params(request)

    with get_connection() as conn:
        rows = _fetch_leads(conn, **{k: v for k, v in p.items() if k != "sort_explicit"})
        leads = [_decorate_row(conn, row) for row in rows]

    def url(**overrides) -> str:
        return _dashboard_url(**{**p, **overrides})

    tab_urls = {key: url(tab=key) for key in _TAB_STATUSES}
    context = {
        "username": admin_username,
        "leads": leads,
        "tabs": _TAB_LABELS,
        "active_tab": p["tab"],
        "tab_urls": tab_urls,
        "show_all": p["show_all"],
        "search": p["search"] or "",
        "sort_oldest_first": p["sort_oldest_first"],
        "channel_filter": p["channel_filter"] or "",
        "bundesland_filter": p["bundesland_filter"] or "",
        "channel_options": CHANNEL_LABELS,
        "bundesland_options": _BUNDESLAENDER,
        "alle_toggle_url": url(show_all=not p["show_all"]),
        "sort_url_aeltest": url(sort_explicit="aeltest"),
        "sort_url_neueste": url(sort_explicit="neueste"),
        "clear_filters_url": url(search=None, channel_filter=None, bundesland_filter=None),
        "csv_export_url": url(path="/admin/export.csv"),
        "channel_labels": CHANNEL_LABELS,
    }
    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context=context)


def _dashboard_url(
    *,
    tab: str,
    show_all: bool,
    search: str | None,
    sort_explicit: str | None,
    channel_filter: str | None = None,
    bundesland_filter: str | None = None,
    path: str = "/admin",
    **_ignored,  # sort_oldest_first u.ä. aus p durchgereicht, hier irrelevant
) -> str:
    params: list[tuple[str, str]] = [("tab", tab)]
    if show_all:
        params.append(("alle", "1"))
    if sort_explicit:
        params.append(("sort", sort_explicit))
    if search:
        params.append(("q", search))
    if channel_filter:
        params.append(("channel", channel_filter))
    if bundesland_filter:
        params.append(("bundesland", bundesland_filter))
    return f"{path}?" + urlencode(params)


def _escape_ilike(term: str) -> str:
    """Escaped ILIKE-Metazeichen im Suchbegriff, damit z.B. ein '%' oder
    '_' in einer Adresse als Literal gesucht wird statt als Wildcard."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fetch_leads(
    conn: psycopg.Connection,
    *,
    tab: str,
    show_all: bool,
    search: str | None,
    sort_oldest_first: bool,
    channel_filter: str | None = None,
    bundesland_filter: str | None = None,
) -> list[dict]:
    conditions: list[str] = []
    params: dict = {}

    tab_statuses = _TAB_STATUSES[tab]
    if tab_statuses is not None:
        conditions.append("l.status = ANY(%(tab_statuses)s)")
        params["tab_statuses"] = tab_statuses

    if not show_all:
        # is_spam wird zusätzlich zum Status geprüft: persist_submission()
        # setzt status nach keiner der vier Dedup-Entscheidungen auf 'spam'
        # (nur is_spam/spam_reason) - ohne diese Zeile blieben spam-markierte
        # Leads mit status='neu' in der Neu-Tab sichtbar, obwohl Konzept §6
        # sie im Standard-Filter versteckt sehen will. Root Cause gehört in
        # submission.py behoben (s. Rückmeldung an Marco), hier nur defensiv
        # abgefangen, damit die Liste schon jetzt korrekt filtert.
        conditions.append("l.status <> ALL(%(hidden_statuses)s) AND NOT l.is_spam")
        params["hidden_statuses"] = _HIDDEN_STATUSES

    if search:
        conditions.append(
            "(l.name ILIKE %(search)s OR l.name_raw ILIKE %(search)s OR l.email ILIKE %(search)s "
            "OR l.phone_raw ILIKE %(search)s OR l.phone_e164 ILIKE %(search)s OR l.city ILIKE %(search)s)"
        )
        params["search"] = f"%{_escape_ilike(search)}%"

    if channel_filter:
        conditions.append("l.channel = %(channel_filter)s")
        params["channel_filter"] = channel_filter

    if bundesland_filter:
        conditions.append("l.geo_state = %(bundesland_filter)s")
        params["bundesland_filter"] = bundesland_filter

    where_sql = " AND ".join(conditions) if conditions else "true"
    order_sql = "l.created_at ASC" if sort_oldest_first else "l.created_at DESC"

    # Alle interpolierten SQL-Fragmente oben stammen aus fest codierten
    # Strings (Tab-/Sort-Auswahl per Dictionary-Lookup) - Nutzereingaben
    # (search, Status-Listen) laufen ausschließlich über %()s-Parameter.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                l.id, l.lead_nummer, l.created_at, l.name, l.name_raw, l.city, l.geo_state, l.geo_country,
                l.channel, l.channel_source, l.heard_about, l.status, l.assigned_to,
                l.is_spam, l.spam_reason, l.in_service_area, l.geocode_status,
                l.phone_raw, l.phone_valid, l.postal_code, l.street,
                l.email, l.is_owner, l.contact_time_preference, l.message,
                l.contacted_at, l.disqualify_reason, l.privacy_accepted_at,
                l.duplicate_of, l.superseded_by,
                (
                    SELECT o.created_at FROM leads o WHERE o.id = l.duplicate_of
                ) AS duplicate_of_created_at,
                (
                    SELECT s.created_at FROM leads s WHERE s.id = l.superseded_by
                ) AS superseded_by_created_at,
                (
                    SELECT p.id FROM leads p WHERE p.superseded_by = l.id LIMIT 1
                ) AS vorgaenger_id,
                (
                    SELECT p.created_at FROM leads p WHERE p.superseded_by = l.id LIMIT 1
                ) AS vorgaenger_created_at,
                EXISTS (
                    SELECT 1 FROM lead_events e
                    WHERE e.lead_id = l.id AND e.event_type = 'kontakt_bekannt'
                ) AS kontakt_bekannt,
                (
                    SELECT max(e.created_at) FROM lead_events e
                    WHERE e.lead_id = l.id AND e.event_type = 'erneut_angefragt'
                ) AS erneut_angefragt_am
            FROM leads l
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT 500
            """,
            params,
        )
        return cur.fetchall()


# Status-Werte, die keine eigenständig zu bearbeitende Anfrage sind, sondern
# ein technisches/historisches Artefakt (Konzept §4/§J) - Zeile in der Liste
# gedämpft dargestellt statt gleichrangig neben aktiven Leads zu stehen
# (Marco, 2026-08-16: "man muss die Logik erraten, statt sie zu sehen").
_INAKTIVE_STATUSWERTE = {"duplikat", "ersetzt", "spam", "ausland"}


def _kette_info(conn: psycopg.Connection, lead_id: str) -> tuple[int, int] | None:
    """(Position, Gesamtlänge) in der superseded_by-Kette, oder None wenn
    dieser Lead weder Vorgänger noch Nachfolger hat. Erst rückwärts zur
    Wurzel (ältester Vorgänger), dann von dort vorwärts die ganze Kette
    einsammeln - dieselbe Wurzel-Logik wie in _fetch_ancestor_chain, nur
    zusätzlich mit Vorwärtslauf für die Gesamtlänge."""
    root_id = lead_id
    for _ in range(50):
        row = conn.execute("SELECT id FROM leads WHERE superseded_by = %(id)s", {"id": root_id}).fetchone()
        if row is None:
            break
        root_id = str(row[0])

    chain_ids = [root_id]
    current_id = root_id
    for _ in range(50):
        row = conn.execute("SELECT superseded_by FROM leads WHERE id = %(id)s", {"id": current_id}).fetchone()
        if row is None or row[0] is None:
            break
        current_id = str(row[0])
        chain_ids.append(current_id)

    if len(chain_ids) < 2:
        return None
    return chain_ids.index(lead_id) + 1, len(chain_ids)


def _duplikatgruppe_info(conn: psycopg.Connection, lead_id: str, duplicate_of) -> tuple[int, int] | None:
    """(Position, Gesamtgröße) der Duplikatgruppe (Original + alle F2-
    Duplikate, chronologisch), oder None wenn dieser Lead weder Original
    mit Duplikaten noch selbst ein Duplikat ist."""
    wurzel = str(duplicate_of) if duplicate_of else lead_id
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id FROM leads WHERE id = %(w)s OR duplicate_of = %(w)s ORDER BY created_at ASC",
            {"w": wurzel},
        )
        rows = cur.fetchall()
    if len(rows) < 2:
        return None
    ids = [str(r["id"]) for r in rows]
    return ids.index(lead_id) + 1, len(ids)


def _decorate_row(conn: psycopg.Connection, row: dict) -> dict:
    result = compute_ampel(
        is_spam=row["is_spam"],
        spam_reason=row["spam_reason"],
        in_service_area=row["in_service_area"],
        geocode_status=row["geocode_status"],
        geo_state=row["geo_state"],
        geo_country=row["geo_country"],
        geocode_candidate_count=None,  # geocode_raw-Struktur erst mit Phase 4 (Nominatim) definiert
        phone_raw=row["phone_raw"],
        phone_valid=row["phone_valid"],
        postal_code=row["postal_code"],
    )

    badges: list[dict] = []

    # Zusammengehörigkeit zuerst, als schnelle Gesamtübersicht ohne den
    # einzelnen Verweisen folgen zu müssen (Marco, 2026-08-16).
    if row["superseded_by"] or row["vorgaenger_id"]:
        kette = _kette_info(conn, str(row["id"]))
        if kette:
            pos, total = kette
            badges.append({"text": f"Teil einer Korrekturkette: Anfrage {pos} von {total}", "url": None})
    dup_gruppe = _duplikatgruppe_info(conn, str(row["id"]), row["duplicate_of"])
    if dup_gruppe:
        pos, total = dup_gruppe
        badges.append({"text": f"Teil einer Duplikatgruppe: Anfrage {pos} von {total}", "url": None})

    if row["erneut_angefragt_am"] is not None:
        badges.append({"text": f"Erneut angefragt am {format_berlin_datetime(row['erneut_angefragt_am'])}", "url": None})
    if row["duplicate_of"] and row["duplicate_of_created_at"] is not None:
        badges.append({
            "text": f"Duplikat von Anfrage vom {format_berlin_datetime(row['duplicate_of_created_at'])}",
            "url": f"/admin/leads/{row['duplicate_of']}",
        })
    if row["superseded_by"] and row["superseded_by_created_at"] is not None:
        badges.append({
            "text": f"Ersetzt durch Anfrage vom {format_berlin_datetime(row['superseded_by_created_at'])}",
            "url": f"/admin/leads/{row['superseded_by']}",
        })
    if row["vorgaenger_id"] and row["vorgaenger_created_at"] is not None:
        badges.append({
            "text": f"Frühere Version vom {format_berlin_datetime(row['vorgaenger_created_at'])}",
            "url": f"/admin/leads/{row['vorgaenger_id']}",
        })
    if row["kontakt_bekannt"]:
        badges.append({"text": "Kontakt bekannt", "url": None})
    if row["phone_raw"] and not row["phone_valid"]:
        badges.append({"text": "Telefon prüfen", "url": None})
    if row["geocode_status"] == "mehrdeutig":
        badges.append({"text": "Adresse mehrdeutig", "url": None})

    return {
        **row,
        "created_at_display": format_berlin_datetime(row["created_at"]),
        "status_display": status_label(row["status"]),
        "ampel_farbe": result.farbe,
        "ampel_grund": result.grund,
        "badges": badges,
        "row_inaktiv": row["status"] in _INAKTIVE_STATUSWERTE,
    }


# --- CSV-Export (Konzept §6/§8 K8, CLAUDE.md Regel 8) ---------------------
# Läuft über dieselben _fetch_leads()/_decorate_row() wie die Liste, damit
# Filter/Suche/Sortierung zwischen Ansicht und Export nie auseinanderlaufen
# können (Marco, 2026-08-16: "berücksichtigt den aktuell aktiven Filter und
# die Suche, nicht immer alles").

_AMPEL_FARBE_LABELS = {"gruen": "Grün", "gelb": "Gelb", "rot": "Rot", "grau": "Grau", "schwarz": "Schwarz"}

_CSV_HEADER = [
    "Lead-Nummer", "Lead-ID", "Erstellt am", "Name", "E-Mail", "Telefon", "Straße", "PLZ", "Ort",
    "Bundesland", "Eigentümer", "Erreichbarkeit", "Wie gefunden", "Anmerkungen",
    "Kanal", "Kanal-Quelle", "Status", "Zugewiesen an", "Kontaktiert am",
    "Disqualifikationsgrund", "Ampel", "Ampel-Grund", "Telefon gültig",
    "PLZ angegeben", "Geocoding-Status", "Im Einzugsgebiet", "Spam-Verdacht",
    "Datenschutz akzeptiert am",
]


@router.get("/export.csv")
def export_leads_csv(request: Request):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    p = _resolve_dashboard_params(request)

    with get_connection() as conn:
        rows = _fetch_leads(conn, **{k: v for k, v in p.items() if k != "sort_explicit"})
        leads = [_decorate_row(conn, row) for row in rows]

    buffer = io.StringIO()
    # Excel (Deutschland) erwartet Semikolon als Trennzeichen (CLAUDE.md
    # Regel 8) - Komma würde bei uns ohnehin mit deutschen Dezimalzahlen
    # kollidieren, hier aber vor allem: Excel öffnet eine komma-getrennte
    # Datei auf einem deutschen System ansonsten als eine einzige Spalte.
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(_CSV_HEADER)
    for lead in leads:
        writer.writerow(_csv_row(lead))

    # utf-8-sig schreibt die BOM automatisch mit - ohne sie interpretiert
    # Excel unter Windows die Datei als Systemcodepage statt UTF-8 und
    # zerlegt jeden Umlaut (CLAUDE.md Regel 8).
    content = buffer.getvalue().encode("utf-8-sig")
    filename = _csv_filename(
        tab=p["tab"], show_all=p["show_all"], search=p["search"],
        channel_filter=p["channel_filter"], bundesland_filter=p["bundesland_filter"],
    )
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9]+")


def _csv_filename(
    *,
    tab: str,
    show_all: bool,
    search: str | None,
    channel_filter: str | None = None,
    bundesland_filter: str | None = None,
) -> str:
    """Dateiname enthält Filter+Suche+Datum, damit mehrere Exporte am
    selben Tag nicht denselben Namen tragen und sich der Browser nicht
    stillschweigend für eine "(1)"-Kopie entscheidet (Marco, 2026-08-16)."""
    parts = ["standort-check-leads", tab]
    if show_all:
        parts.append("inkl-inaktive")
    if channel_filter:
        parts.append(f"kanal-{_FILENAME_UNSAFE_RE.sub('-', channel_filter).strip('-').lower()}")
    if bundesland_filter:
        parts.append(f"bundesland-{_FILENAME_UNSAFE_RE.sub('-', bundesland_filter).strip('-').lower()}")
    if search:
        slug = _FILENAME_UNSAFE_RE.sub("-", search).strip("-").lower()
        if slug:
            parts.append(f"suche-{slug[:30]}")
    parts.append(berlin_today_iso())
    return "-".join(parts) + ".csv"


def _csv_ja_nein(value: bool | None) -> str:
    return {True: "Ja", False: "Nein"}.get(value, "")


def _csv_text(value) -> str:
    return str(value) if value not in (None, "") else ""


def _csv_dt(value) -> str:
    return format_berlin_datetime(value) if value is not None else ""


def _csv_row(lead: dict) -> list[str]:
    return [
        _csv_text(lead["lead_nummer"]),
        str(lead["id"]),
        _csv_dt(lead["created_at"]),
        _csv_text(lead["name_raw"]),
        _csv_text(lead["email"]),
        _csv_text(lead["phone_raw"]),
        _csv_text(lead["street"]),
        _csv_text(lead["postal_code"]),
        _csv_text(lead["city"]),
        _csv_text(lead["geo_state"]),
        _csv_ja_nein(lead["is_owner"]),
        CONTACT_TIME_LABELS.get(lead["contact_time_preference"], ""),
        _csv_text(lead["heard_about"]),
        _csv_text(lead["message"]),
        CHANNEL_LABELS.get(lead["channel"], _csv_text(lead["channel"])),
        _csv_text(lead["channel_source"]),
        lead["status_display"],
        _csv_text(lead["assigned_to"]),
        _csv_dt(lead["contacted_at"]),
        _csv_text(lead["disqualify_reason"]),
        _AMPEL_FARBE_LABELS.get(lead["ampel_farbe"], lead["ampel_farbe"]),
        lead["ampel_grund"],
        _csv_ja_nein(lead["phone_valid"]) if lead["phone_raw"] else "",
        _csv_ja_nein(lead["postal_code"] is not None),
        status_label(lead["geocode_status"]),
        _csv_ja_nein(lead["in_service_area"]),
        _csv_ja_nein(lead["is_spam"]),
        _csv_dt(lead["privacy_accepted_at"]),
    ]


# --- Detailansicht (Konzept §6) ------------------------------------------


@router.get("/leads/{lead_id}")
def lead_detail(request: Request, lead_id: str):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lead nicht gefunden.")

    with get_connection() as conn:
        row = _fetch_lead(conn, lead_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Lead nicht gefunden.")
        ancestors = _fetch_ancestor_chain(conn, lead_id)
        # str() auf jede id: psycopg liefert leads.id als UUID-Objekt zurück,
        # lead_id (Pfad-Parameter) ist ein plain str - eine gemischte Liste
        # kann psycopg nicht als Array-Parameter adaptieren (DataError).
        chain_ids = [str(a["id"]) for a in ancestors] + [lead_id]
        events = _fetch_events(conn, chain_ids)
        duplicate_of_row = _fetch_lead_summary(conn, row["duplicate_of"]) if row["duplicate_of"] else None
        superseded_by_row = _fetch_lead_summary(conn, row["superseded_by"]) if row["superseded_by"] else None

    context = _build_detail_context(row, ancestors, events, duplicate_of_row, superseded_by_row)
    context["username"] = admin_username
    context["aktion_feedback"] = request.query_params.get("aktion")
    return templates.TemplateResponse(request=request, name="admin_lead_detail.html", context=context)


def _fetch_lead(conn: psycopg.Connection, lead_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM leads WHERE id = %(id)s", {"id": lead_id})
        return cur.fetchone()


def _fetch_lead_summary(conn: psycopg.Connection, lead_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, created_at, name, email, street, city FROM leads WHERE id = %(id)s",
            {"id": lead_id},
        )
        return cur.fetchone()


def _fetch_ancestor_chain(conn: psycopg.Connection, lead_id: str) -> list[dict]:
    """Läuft rückwärts durch die superseded_by-Kette (Konzept §4 F3): alle
    Vorgänger-Versionen, die (ggf. über mehrere Korrekturen) zum aktuell
    betrachteten Lead geführt haben. Älteste zuerst - im Dashboard
    "ausgegraut darunter" (Konzept §6). Jeder Lead hat höchstens einen
    direkten Nachfolger (_find_dedup_candidate wählt genau einen Kandidaten),
    die Kette ist also linear, kein Baum."""
    ancestors: list[dict] = []
    current_id = lead_id
    with conn.cursor(row_factory=dict_row) as cur:
        for _ in range(50):  # Sicherheitsnetz analog resolve_current_lead() in submission.py
            cur.execute(
                """
                SELECT id, created_at, name, email, phone_raw, street, postal_code, city, status
                FROM leads WHERE superseded_by = %(id)s
                """,
                {"id": current_id},
            )
            row = cur.fetchone()
            if row is None:
                break
            ancestors.append(row)
            current_id = row["id"]
    ancestors.reverse()
    return ancestors


def _fetch_events(conn: psycopg.Connection, lead_ids: list[str]) -> list[dict]:
    """Event-Historie über die GESAMTE superseded-Kette, nicht nur den
    aktuellen Datensatz: bei einer Korrektur (F3) hängt das 'ersetzt'-Event
    am alten lead_id, das folgende 'mail_gesendet' etc. am neuen - erst die
    Vereinigung ergibt die vollständige Geschichte dieses Leads."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT lead_id, event_type, payload, created_at
            FROM lead_events
            WHERE lead_id = ANY(%(ids)s)
            ORDER BY created_at ASC
            """,
            {"ids": lead_ids},
        )
        return cur.fetchall()


def _ja_nein(value: bool | None) -> str:
    return {True: "Ja", False: "Nein"}.get(value, "–")


def _text(value) -> str:
    return str(value) if value not in (None, "") else "–"


def _dt(value) -> str:
    return format_berlin_datetime(value) if value is not None else "–"


def _field_groups(row: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    """Alle Lead-Spalten außer message/duplicate_of/superseded_by/
    traffic_light(_reason)/status/assigned_to/disqualify_reason/
    contacted_at - message steht prominent oben, duplicate_of/superseded_by
    als Banner, traffic_light wird live über app.core.ampel berechnet statt
    der (vor Phase 4 ohnehin leeren) Cache-Spalte gezeigt, und die
    Bearbeitungsfelder stehen als eigenes editierbares Formular (Aktionen)
    statt in dieser reinen Anzeige-Liste. "Alle Felder, auch leere" (Marco,
    2026-08-16): jede Zeile erscheint immer, mit "–" statt Auslassung wenn
    leer."""
    name_value = row["name"] or "–"
    if row["name_normalized"] and row["name_raw"]:
        name_value += f" (wie eingegeben: {row['name_raw']})"

    email_value = row["email"]
    if row["email_normalized"] and row["email_normalized"] != row["email"]:
        email_value += f" (normalisiert: {row['email_normalized']})"

    if row["phone_raw"]:
        if row["phone_valid"] and row["phone_e164"]:
            phone_value = f"{row['phone_raw']} (gültig, E.164: {row['phone_e164']})"
        else:
            phone_value = f"{row['phone_raw']} (nicht als gültige Nummer erkannt)"
    else:
        phone_value = "–"

    maps_link = "– (noch nicht geokodiert)"
    if row["lat"] is not None and row["lon"] is not None:
        maps_link = f"https://maps.google.com/?q={row['lat']},{row['lon']}"

    koordinaten = f"{row['lat']}, {row['lon']}" if row["lat"] is not None else "–"

    return [
        ("Kontakt", [
            ("Name", name_value),
            ("E-Mail", email_value),
            ("Telefon", phone_value),
        ]),
        ("Adresse (Grundstück)", [
            ("Straße", _text(row["street"])),
            ("PLZ", _text(row["postal_code"])),
            ("Ort", _text(row["city"])),
            ("Bundesland", _text(row["geo_state"])),
            ("Land", _text(row["geo_country"])),
            ("Karten-Link", maps_link),
        ]),
        ("Fachliche Angaben", [
            ("Eigentümer des Grundstücks?", _ja_nein(row["is_owner"])),
            ("Erreichbarkeit", CONTACT_TIME_LABELS.get(row["contact_time_preference"], "–")),
            ("Wie gefunden", _text(row["heard_about"])),
        ]),
        ("Herkunft", [
            ("Kanal", CHANNEL_LABELS.get(row["channel"], _text(row["channel"]))),
            ("Kanal-Quelle", _text(row["channel_source"])),
            ("UTM Source", _text(row["utm_source"])),
            ("UTM Medium", _text(row["utm_medium"])),
            ("UTM Campaign", _text(row["utm_campaign"])),
            ("UTM Term", _text(row["utm_term"])),
            ("UTM Content", _text(row["utm_content"])),
            ("Google Click ID (gclid)", _text(row["gclid"])),
            ("Facebook Click ID (fbclid)", _text(row["fbclid"])),
            ("Referrer", _text(row["referrer"])),
            ("Landingpage", _text(row["landing_page"])),
        ]),
        ("Spam-Prüfung", [
            ("Spamverdacht?", _ja_nein(row["is_spam"])),
            ("Grund", SPAM_REASON_LABELS.get(row["spam_reason"], _text(row["spam_reason"]))),
        ]),
        ("Bestätigungsmail", [
            ("Status", status_label(row["email_status"])),
            ("Versuche", str(row["email_attempts"])),
            ("Letzter Fehler", _text(row["email_last_error"])),
            ("Gesendet am", _dt(row["email_sent_at"])),
            ("Auslandshinweis-Status", status_label(row["ausland_hinweis_status"])),
            ("Interesse an Erweiterung ins Ausland", _ja_nein(row["expansion_opt_in"])),
        ]),
        ("Geocoding", [
            ("Status", status_label(row["geocode_status"])),
            ("Versuche", str(row["geocode_attempts"])),
            ("Koordinaten", koordinaten),
            ("Gemeinde", _text(row["geo_municipality"])),
            ("Im Einzugsgebiet?", _ja_nein(row["in_service_area"])),
            ("Rohdaten (Nominatim)", _text(row["geocode_raw"])),
        ]),
        ("Datenschutz & Zeiten", [
            ("Datenschutz akzeptiert am", _dt(row["privacy_accepted_at"])),
            ("Verarbeitung ab", _dt(row["process_after"])),
            ("Erstellt am", _dt(row["created_at"])),
            ("Zuletzt geändert", _dt(row["updated_at"])),
        ]),
        ("Technisch", [
            ("Lead-ID", str(row["id"])),
            ("Submission-Token", str(row["submission_token"])),
            ("Content-Hash", row["content_hash"]),
        ]),
    ]


def _build_detail_context(
    row: dict,
    ancestors: list[dict],
    events: list[dict],
    duplicate_of_row: dict | None,
    superseded_by_row: dict | None,
) -> dict:
    result = compute_ampel(
        is_spam=row["is_spam"],
        spam_reason=row["spam_reason"],
        in_service_area=row["in_service_area"],
        geocode_status=row["geocode_status"],
        geo_state=row["geo_state"],
        geo_country=row["geo_country"],
        geocode_candidate_count=None,
        phone_raw=row["phone_raw"],
        phone_valid=row["phone_valid"],
        postal_code=row["postal_code"],
    )

    ancestors_display = [
        {
            **a,
            "created_at_display": format_berlin_datetime(a["created_at"]),
        }
        for a in ancestors
    ]

    if duplicate_of_row is not None:
        duplicate_of_row = {**duplicate_of_row, "created_at_display": format_berlin_datetime(duplicate_of_row["created_at"])}
    if superseded_by_row is not None:
        superseded_by_row = {**superseded_by_row, "created_at_display": format_berlin_datetime(superseded_by_row["created_at"])}

    events_display = [
        {
            **e,
            "created_at_display": format_berlin_datetime(e["created_at"]),
            "label": EVENT_TYPE_LABELS.get(e["event_type"], e["event_type"]),
        }
        for e in events
    ]

    return {
        "lead": row,
        "lead_id": row["id"],
        "created_at_display": format_berlin_datetime(row["created_at"]),
        "status_display": status_label(row["status"]),
        "contacted_at_display": _dt(row["contacted_at"]),
        "email_status_display": status_label(row["email_status"]),
        "ampel_farbe": result.farbe,
        "ampel_grund": result.grund,
        "message": row["message"],
        "field_groups": _field_groups(row),
        "ancestors": ancestors_display,
        "events": events_display,
        "duplicate_of_row": duplicate_of_row,
        "superseded_by_row": superseded_by_row,
        "manually_settable_statuses": [(value, status_label(value)) for value in _MANUALLY_SETTABLE_STATUSES],
    }


# --- Aktionen (Konzept §6) -------------------------------------------------
# Dashboard-Buttons "Geocoding erneut" (einzeln) / globaler Retry-Button
# bewusst noch nicht gebaut - das ist Phase 4 Block (d). POST /admin/retry
# (unten, Block b) existiert bereits als Backend-Endpunkt und ist schon
# heute per curl/GitHub-Actions-Cron nutzbar.


@router.post("/leads/{lead_id}/bearbeitung")
def update_lead_bearbeitung(
    request: Request,
    lead_id: str,
    status: str = Form(...),
    assigned_to: str = Form(""),
    disqualify_reason: str = Form(""),
):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    if status not in _MANUALLY_SETTABLE_STATUSES:
        raise HTTPException(status_code=400, detail="Ungültiger Status.")

    assigned_to = assigned_to.strip() or None
    disqualify_reason = disqualify_reason.strip() or None

    with get_connection() as conn:
        row = _fetch_lead(conn, lead_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Lead nicht gefunden.")

        updates: dict = {}

        if status != row["status"]:
            updates["status"] = status
            insert_event(conn, lead_id, "status_geaendert", {"von": row["status"], "nach": status})

        # is_spam/spam_reason/contacted_at richten sich nach dem EINGEREICHTEN
        # status, nicht danach, ob sich status gegenüber der DB geändert hat -
        # sonst bliebe ein bereits inkonsistenter Altdatensatz (is_spam=true
        # bei status='neu', aus der Zeit vor dem Spam/Dedup-Fix, s.
        # docs/TODO.md "Beim Bauen gefunden") inkonsistent, wenn genau dieser
        # Status erneut abgeschickt wird ("neu" -> "neu" wäre keine Änderung,
        # is_spam bliebe fälschlich true). Konzept §J: ein Fehlalarm der
        # Spam-Erkennung muss "manuell freigegeben werden" können -
        # send_confirmation_email() prüft is_spam (nicht status), ohne diese
        # Zeile bliebe die Mail auch nach Freigabe blockiert. Symmetrisch:
        # wird manuell auf 'spam' gesetzt, muss is_spam mitziehen, sonst
        # ignorieren Ampel/Dashboard-Filter/Mail-Versand die manuelle
        # Einstufung.
        if status == "spam" and not row["is_spam"]:
            updates["is_spam"] = True
            updates["spam_reason"] = "manuell_markiert"
        elif status != "spam" and row["is_spam"]:
            updates["is_spam"] = False

        if status == "kontaktiert" and row["contacted_at"] is None:
            updates["contacted_at"] = datetime.now(timezone.utc)

        if assigned_to != row["assigned_to"]:
            updates["assigned_to"] = assigned_to
            insert_event(conn, lead_id, "zugewiesen", {"an": assigned_to})

        if disqualify_reason != row["disqualify_reason"]:
            updates["disqualify_reason"] = disqualify_reason

        if updates:
            _update_lead(conn, lead_id, updates)

    return RedirectResponse(url=f"/admin/leads/{lead_id}?aktion=gespeichert", status_code=303)


@router.post("/leads/{lead_id}/mail-erneut-senden")
def resend_lead_mail(request: Request, lead_id: str):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    with get_connection() as conn:
        row = _fetch_lead(conn, lead_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Lead nicht gefunden.")
        data = row_to_new_lead_data(row)

    aktion = "mail_gesendet"
    try:
        with get_connection() as conn:
            send_confirmation_email(conn, lead_id, data, str(request.base_url), DedupCase.NEU)
    except Exception:
        # Admin-Aktion, kein Submit-Pfad - CLAUDE.md Regel 2 gilt hier nicht
        # wörtlich, aber ein rohes 500 für einen Klick auf "erneut senden"
        # wäre trotzdem schlechtes Verhalten. send_confirmation_email fängt
        # Brevo-/Netzwerkfehler schon selbst ab; dieser Fang ist nur das
        # Netz für alles andere (z.B. DB-Fehler beim Status-Update).
        logger.exception("Manueller Mail-Resend fehlgeschlagen für Lead %s", lead_id)
        aktion = "mail_fehler"

    return RedirectResponse(url=f"/admin/leads/{lead_id}?aktion={aktion}", status_code=303)


def _update_lead(conn: psycopg.Connection, lead_id: str, updates: dict) -> None:
    # Spaltennamen in `updates` kommen ausschließlich aus fest im Code
    # stehenden Strings oben (status/is_spam/spam_reason/contacted_at/
    # assigned_to/disqualify_reason), nie direkt aus Request-Daten - die
    # f-String-Interpolation der Spaltennamen ist damit unproblematisch,
    # alle WERTE laufen über %()s-Parameter.
    set_clauses = ", ".join(f"{column} = %({column})s" for column in updates)
    conn.execute(
        f"UPDATE leads SET {set_clauses}, updated_at = now() WHERE id = %(lead_id)s",
        {**updates, "lead_id": lead_id},
    )


# --- Retry (Konzept §1/§G, Phase 4 Block b) --------------------------------
# Zwei mögliche Aufrufer (Konzept §1): eingeloggter Admin über den Dashboard-
# Button (Block d, noch nicht gebaut) ODER der GitHub-Actions-Cron (Block e,
# noch nicht gebaut) ohne Session - deshalb zwei akzeptierte Nachweise statt
# nur des Cookies. Antwort ist bewusst JSON statt eines Redirects: welche
# Darstellung ein künftiger Dashboard-Button daraus macht, ist Block (d)s
# Entscheidung, nicht diese hier vorwegzunehmen.


def _authorized_for_retry(request: Request) -> bool:
    if _current_admin(request):
        return True
    return verify_retry_secret(
        request.headers.get("X-Retry-Secret"), expected=os.environ.get("RETRY_SECRET")
    )


@router.post("/retry")
def trigger_retry(request: Request):
    if not _authorized_for_retry(request):
        raise HTTPException(status_code=401, detail="Nicht autorisiert.")
    return run_retry(base_url=str(request.base_url))


# --- Auswertung (Konzept §7) -----------------------------------------------
# Gruppiert nach `channel`, nicht dem in §7 wörtlich genannten `utm_source` -
# §H (später geschrieben, überschreibt §7 bewusst) verlangt ausdrücklich
# "eine einzige verlässliche Spalte" für die Auswertung, das ist channel.
# "Anfragen" (Volumen) zählt JEDE Zeile, auch duplikat/ersetzt/spam - eine
# echte Submission über einen Kanal, unabhängig vom späteren Dedup-/Spam-
# Status. Qualifiziert/Disqualifiziert/Offen sind dagegen nur die drei
# echten Pipeline-Zustände (Offen = neu+kontaktiert); sie summieren sich
# deshalb NICHT zu "Anfragen", sondern zu "Anfragen minus duplikat/ersetzt/
# spam/ausland" - eine andere Frage (Volumen vs. Pipeline-Stand).
# Alle Quoten/Prozent-Spalten teilen dieselbe Basis (Anfragen), damit "Basis:
# n" pro Zeile eindeutig ist (Konzept §7 Ehrlichkeits-Hinweis) - nur die
# Qualifizierungsquote hat bewusst einen anderen Nenner (nur entschiedene
# Fälle), weil sie eine andere Frage beantwortet ("taugt der Kanal" statt
# "wie ist die Datenqualität im gesamten Traffic").

_GRUPPIERUNGEN = {
    "channel": ("Kanal", "channel"),
    "campaign": ("Kampagne", "utm_campaign"),
    "heard_about": ("Wie gefunden", "heard_about"),
    "bundesland": ("Bundesland", "geo_state"),
}
_DEFAULT_GRUPPIERUNG = "channel"
_MIN_BASIS_FUER_QUOTEN = 10


@router.get("/auswertung")
def auswertung(request: Request):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    gruppierung = request.query_params.get("gruppieren_nach", _DEFAULT_GRUPPIERUNG)
    if gruppierung not in _GRUPPIERUNGEN:
        gruppierung = _DEFAULT_GRUPPIERUNG
    _, group_column = _GRUPPIERUNGEN[gruppierung]

    with get_connection() as conn:
        rows = _fetch_auswertung(conn, group_column)
        kreuztabelle = _fetch_kreuztabelle(conn)

    zeilen = [_decorate_auswertung_row(r) for r in rows]
    gesamt_anfragen = sum(r["anfragen"] for r in zeilen)

    context = {
        "username": admin_username,
        "gruppierungen": _GRUPPIERUNGEN,
        "aktive_gruppierung": gruppierung,
        "zeilen": zeilen,
        "gesamt_anfragen": gesamt_anfragen,
        "kreuztabelle": kreuztabelle,
        "min_basis": _MIN_BASIS_FUER_QUOTEN,
        "channel_labels": CHANNEL_LABELS,
    }
    return templates.TemplateResponse(request=request, name="admin_auswertung.html", context=context)


def _fetch_auswertung(conn: psycopg.Connection, group_column: str) -> list[dict]:
    # group_column kommt ausschließlich aus dem festen _GRUPPIERUNGEN-Dict
    # oben (Whitelist-Lookup über gruppieren_nach), nie direkt aus der
    # Request - sicher trotz f-String-Interpolation des Spaltennamens.
    # NULLIF(..., ''): utm_campaign (anders als heard_about/phone/name) wird
    # beim Submit NICHT von leer-String auf NULL normalisiert (main.py), das
    # hidden Formularfeld schickt bei fehlendem UTM-Parameter value="" statt
    # gar nichts. Ohne NULLIF entstünden zwei optisch identische "(keine
    # Angabe)"-Zeilen für NULL und '' - eine echte, aber andere Gruppe, nur
    # unsichtbar gemacht (Fund beim Bauen, s. Rückmeldung an Marco).
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                NULLIF({group_column}, '') AS gruppe,
                count(*) AS anfragen,
                count(*) FILTER (WHERE status IN ('neu', 'kontaktiert')) AS offen,
                count(*) FILTER (WHERE status = 'qualifiziert') AS qualifiziert,
                count(*) FILTER (WHERE status = 'disqualifiziert') AS disqualifiziert,
                count(*) FILTER (WHERE is_owner = true) AS eigentuemer_ja,
                count(*) FILTER (WHERE is_owner IS NOT NULL) AS eigentuemer_angabe,
                avg(contacted_at - created_at) FILTER (WHERE contacted_at IS NOT NULL) AS zeit_bis_kontakt,
                count(*) FILTER (
                    WHERE phone_raw IS NOT NULL AND phone_raw <> '' AND NOT phone_valid
                ) AS telefon_unlesbar,
                count(*) FILTER (WHERE geocode_status IN ('mehrdeutig', 'nicht_gefunden')) AS adresse_unklar,
                count(*) FILTER (WHERE is_spam) AS spam
            FROM leads
            GROUP BY NULLIF({group_column}, '')
            ORDER BY anfragen DESC, gruppe ASC NULLS LAST
            """
        )
        return cur.fetchall()


def _fetch_kreuztabelle(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT channel, geo_state, count(*) AS anzahl
            FROM leads
            GROUP BY channel, geo_state
            """
        )
        rows = cur.fetchall()

    kanaele = sorted({r["channel"] or "(keine Angabe)" for r in rows})
    bundeslaender = sorted({r["geo_state"] or "(keine Angabe)" for r in rows})
    matrix = {k: {b: 0 for b in bundeslaender} for k in kanaele}
    for r in rows:
        k = r["channel"] or "(keine Angabe)"
        b = r["geo_state"] or "(keine Angabe)"
        matrix[k][b] = r["anzahl"]

    return {"kanaele": kanaele, "bundeslaender": bundeslaender, "matrix": matrix}


def _quote(zaehler: int, nenner: int) -> str:
    if nenner == 0:
        return "–"
    return f"{round(100 * zaehler / nenner)}%"


def _decorate_auswertung_row(row: dict) -> dict:
    anfragen = row["anfragen"]
    entschieden = row["qualifiziert"] + row["disqualifiziert"]
    return {
        "gruppe": row["gruppe"] or "(keine Angabe)",
        "anfragen": anfragen,
        "offen": row["offen"],
        "qualifiziert": row["qualifiziert"],
        "disqualifiziert": row["disqualifiziert"],
        "qualifizierungsquote": _quote(row["qualifiziert"], entschieden),
        "eigentuemer_anteil": _quote(row["eigentuemer_ja"], row["eigentuemer_angabe"]),
        "zeit_bis_kontakt": format_duration_de(row["zeit_bis_kontakt"]),
        "telefon_unlesbar_pct": _quote(row["telefon_unlesbar"], anfragen),
        "adresse_unklar_pct": _quote(row["adresse_unklar"], anfragen),
        "spam_pct": _quote(row["spam"], anfragen),
        "niedrige_basis": anfragen < _MIN_BASIS_FUER_QUOTEN,
    }
