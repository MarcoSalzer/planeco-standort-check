"""Admin-Dashboard: Login + Lead-Liste (Konzept §6). Detailansicht/Aktionen/
CSV/Auswertung folgen noch.

Session per signiertem Cookie (itsdangerous, SESSION_SECRET - eigenes
Secret, getrennt von EDIT_TOKEN_SECRET, s. app/core/admin_auth.py).
"""
import logging
import os
from urllib.parse import urlencode

import psycopg
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from psycopg.rows import dict_row

from app.core.admin_auth import (
    SESSION_MAX_AGE_SECONDS,
    generate_session_token,
    verify_credentials,
    verify_session_token,
)
from app.core.ampel import ampel as compute_ampel
from app.core.channel import CHANNEL_LABELS
from app.core.display import format_berlin_datetime
from app.db import get_connection
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

# duplicate/superseded/spam/ausland: nicht Teil der normalen Sales-Warte-
# schlange (Konzept §4, §A), default ausgeblendet, Toggle "alles anzeigen".
_HIDDEN_STATUSES = ["duplikat", "ersetzt", "spam", "ausland"]


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


@router.get("")
def dashboard(request: Request):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    tab = request.query_params.get("tab", _DEFAULT_TAB)
    if tab not in _TAB_STATUSES:
        tab = _DEFAULT_TAB
    show_all = request.query_params.get("alle") == "1"
    search = (request.query_params.get("q") or "").strip() or None
    sort_oldest_first = request.query_params.get("sort") != "neueste"

    with get_connection() as conn:
        rows = _fetch_leads(conn, tab=tab, show_all=show_all, search=search, sort_oldest_first=sort_oldest_first)
    leads = [_decorate_row(row) for row in rows]

    tab_urls = {
        key: _dashboard_url(tab=key, show_all=show_all, search=search, sort_oldest_first=sort_oldest_first)
        for key in _TAB_STATUSES
    }
    context = {
        "username": admin_username,
        "leads": leads,
        "tabs": _TAB_LABELS,
        "active_tab": tab,
        "tab_urls": tab_urls,
        "show_all": show_all,
        "search": search or "",
        "sort_oldest_first": sort_oldest_first,
        "alle_toggle_url": _dashboard_url(
            tab=tab, show_all=not show_all, search=search, sort_oldest_first=sort_oldest_first
        ),
        "sort_toggle_url": _dashboard_url(
            tab=tab, show_all=show_all, search=search, sort_oldest_first=not sort_oldest_first
        ),
        "clear_search_url": _dashboard_url(tab=tab, show_all=show_all, search=None, sort_oldest_first=sort_oldest_first),
        "channel_labels": CHANNEL_LABELS,
    }
    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context=context)


def _dashboard_url(*, tab: str, show_all: bool, search: str | None, sort_oldest_first: bool) -> str:
    params: list[tuple[str, str]] = [("tab", tab)]
    if show_all:
        params.append(("alle", "1"))
    if not sort_oldest_first:
        params.append(("sort", "neueste"))
    if search:
        params.append(("q", search))
    return "/admin?" + urlencode(params)


def _escape_ilike(term: str) -> str:
    """Escaped ILIKE-Metazeichen im Suchbegriff, damit z.B. ein '%' oder
    '_' in einer Adresse als Literal gesucht wird statt als Wildcard."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fetch_leads(
    conn: psycopg.Connection, *, tab: str, show_all: bool, search: str | None, sort_oldest_first: bool
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

    where_sql = " AND ".join(conditions) if conditions else "true"
    order_sql = "l.created_at ASC" if sort_oldest_first else "l.created_at DESC"

    # Alle interpolierten SQL-Fragmente oben stammen aus fest codierten
    # Strings (Tab-/Sort-Auswahl per Dictionary-Lookup) - Nutzereingaben
    # (search, Status-Listen) laufen ausschließlich über %()s-Parameter.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                l.id, l.created_at, l.name, l.city, l.geo_state, l.geo_country,
                l.channel, l.heard_about, l.status, l.assigned_to,
                l.is_spam, l.spam_reason, l.in_service_area, l.geocode_status,
                l.phone_raw, l.phone_valid, l.postal_code,
                EXISTS (
                    SELECT 1 FROM leads p WHERE p.superseded_by = l.id
                ) AS wurde_aktualisiert,
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


def _decorate_row(row: dict) -> dict:
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

    badges: list[str] = []
    if row["erneut_angefragt_am"] is not None:
        badges.append(f"Erneut angefragt am {format_berlin_datetime(row['erneut_angefragt_am'])}")
    if row["wurde_aktualisiert"]:
        badges.append(f"Vom Kunden aktualisiert am {format_berlin_datetime(row['created_at'])}")
    if row["kontakt_bekannt"]:
        badges.append("Kontakt bekannt")
    if row["phone_raw"] and not row["phone_valid"]:
        badges.append("Telefon prüfen")
    if row["geocode_status"] == "mehrdeutig":
        badges.append("Adresse mehrdeutig")

    return {
        **row,
        "created_at_display": format_berlin_datetime(row["created_at"]),
        "ampel_farbe": result.farbe,
        "ampel_grund": result.grund,
        "badges": badges,
    }
