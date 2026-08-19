"""Admin-Dashboard: Login + Lead-Liste + Detailansicht + Aktionen + CSV-
Export + Auswertung (Konzept §6/§7). Damit ist Phase 3 vollständig.

Session per signiertem Cookie (itsdangerous, SESSION_SECRET - eigenes
Secret, getrennt von EDIT_TOKEN_SECRET, s. app/core/admin_auth.py).
"""
import csv
import io
import logging
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import psycopg
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from markupsafe import Markup
from psycopg.rows import dict_row
from starlette.datastructures import QueryParams

from app.core.admin_auth import (
    SESSION_MAX_AGE_SECONDS,
    generate_session_token,
    verify_credentials,
    verify_retry_secret,
    verify_session_token,
)
from app.core.channel import CHANNEL_LABELS
from app.core.dedup import DedupCase
from app.core.display import (
    CONTACT_TIME_LABELS,
    EVENT_TYPE_LABELS,
    berlin_today_iso,
    format_address,
    format_berlin_datetime,
    format_duration_de,
    status_label,
)
from app.core.geocoding import GERMAN_STATES, candidate_summaries
from app.core.spam import SPAM_REASON_LABELS
from app.db import get_connection, insert_event
from app.env import get_env
from app.mail import send_confirmation_email
from app.retry import count_leads_im_korrekturfenster, count_wartende_leads, retry_one_geocode, run_retry
from app.submission import NewLeadData, row_to_new_lead_data
from app.templating import templates
from app.traffic_light import apply_traffic_light

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
# abarbeiten). Erledigt bleibt neueste zuerst (Nachschlagewerk). Alle
# sortiert standardmäßig nach Lead-Nummer absteigend (innerhalb derselben
# Nummer Eingangszeit aufsteigend als Tiebreaker, damit zusammengehörige
# Zeilen in sich sortiert stehen, nicht nur zufällig benachbart) - dort
# liegen zusammengehörige Zeilen sonst oft zeitlich weit auseinander, weil
# dazwischen andere Anfragen eingegangen sind (Marco, 2026-08-17: "Thomas
# Ahrens hat zweimal die 12... stehen deshalb in der Liste nicht
# nebeneinander"). Lead-Nummer ist wie die anderen beiden Modi in beide
# Richtungen anklickbar (Marco, 2026-08-18) - kein Sonderfall "Vorgang"
# mehr, seit die Gruppen-Einfärbung entfiel (s. docs/FUNDE.md-Eintrag vom
# selben Tag: bei ausgeblendeten Duplikaten/Ersetzt-Zeilen bestand jede
# Gruppe ohnehin nur aus einer Zeile).
# Per ?sort=aeltest|neueste|nummer_auf|nummer_ab explizit umschaltbar,
# sonst Tab-Default.
_SORT_MODE_SQL = {
    "aeltest": "l.created_at ASC",
    "neueste": "l.created_at DESC",
    "nummer_auf": "l.lead_nummer ASC NULLS LAST, l.created_at ASC",
    "nummer_ab": "l.lead_nummer DESC NULLS LAST, l.created_at ASC",
}
_TAB_DEFAULT_SORT_MODE = {
    "neu": "aeltest",
    "bearbeitung": "aeltest",
    "erledigt": "neueste",
    "alle": "nummer_ab",
}

# duplicate/superseded/spam/ausland: nicht Teil der normalen Sales-Warte-
# schlange (Konzept §4, §A). In Neu/Bearbeitung/Erledigt weiterhin default
# ausgeblendet (Toggle "alles anzeigen"). Im Tab "Alle" seit 2026-08-18
# umgekehrt: Default ist AN (der Tab heißt "Alle", zeigt also alles),
# Toggle blendet dort aus - s. _resolve_dashboard_params.
_HIDDEN_STATUSES = ["duplikat", "ersetzt", "spam", "ausland"]

# Spaltenfilter (Marco, 2026-08-17, ersetzt die zwei Dropdowns über der
# Liste): Ort/Bundesland/Kanal/Status/Zugewiesen werden aus den tatsächlich
# vorhandenen Werten befüllt (_distinct_values, unten) - "kommt aktuell
# nicht vor" soll nicht mit "gibt es nicht" verwechselt werden. Ampel ist
# die eine Ausnahme: eine feste, kleine Liste statt einer DISTINCT-Query
# auf traffic_light, damit 'defekt' (Python-only Fallback, nie in der
# Spalte gespeichert - s. Filterlogik in _fetch_leads) immer als Option
# erscheint, auch wenn gerade keine defekte Zeile existiert.
_AMPEL_FARBEN = ["gruen", "gelb", "rot", "grau", "schwarz", "defekt"]
_AMPEL_FARBE_LABELS_FILTER = {
    "gruen": "Grün", "gelb": "Gelb", "rot": "Rot", "grau": "Grau",
    "schwarz": "Schwarz", "defekt": "Fehler (Anzeige defekt)",
}

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
    secret = get_env("SESSION_SECRET")
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
    admin_user = get_env("ADMIN_USER")
    admin_password_hash = get_env("ADMIN_PASSWORD_HASH")
    session_secret = get_env("SESSION_SECRET")

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


def _resolve_dashboard_params(query_params) -> dict:
    """query_params: alles mit einer dict-artigen .get(key, default) -
    Methode (Request.query_params ODER ein aus einem beliebigen String
    gebautes starlette.datastructures.QueryParams). Letzteres braucht die
    Schnellbearbeitung (Punkt 2, Marco 2026-08-18): dieselbe Filterauflösung
    UND dieselbe _fetch_leads()-WHERE-Logik wie die Liste selbst prüfen,
    ob eine gerade geänderte Zeile noch zum Filter passt, unter dem die
    Änderung ausgelöst wurde - statt einer zweiten, separat gepflegten
    Nachbildung dieser Logik (dasselbe Prinzip wie beim CSV-Export, der
    _fetch_leads()/_decorate_row() bereits mit der Liste teilt)."""
    tab = query_params.get("tab", _DEFAULT_TAB)
    if tab not in _TAB_STATUSES:
        tab = _DEFAULT_TAB

    sort_param = query_params.get("sort")
    if sort_param in _SORT_MODE_SQL:
        sort_mode, sort_explicit = sort_param, sort_param
    else:
        # Kein expliziter Wunsch -> Tab-Default, s. _TAB_DEFAULT_SORT_MODE.
        sort_mode, sort_explicit = _TAB_DEFAULT_SORT_MODE.get(tab, "aeltest"), None

    # show_all: derselbe explizit/Default-Mechanismus wie beim Sortiermodus
    # oben, weil der Default jetzt vom Tab abhängt (Marco, 2026-08-18): "Alle"
    # zeigt inaktive Zeilen (Duplikate/Ersetzt/Spam/Ausland) standardmäßig,
    # die anderen drei Tabs blenden sie standardmäßig aus. "0"/"1" statt nur
    # Anwesenheit des Parameters, damit der Toggle im Tab "Alle" auch explizit
    # AUSblenden kann (bloßes Fehlen des Parameters hieße sonst überall "Default").
    alle_param = query_params.get("alle")
    if alle_param in ("0", "1"):
        show_all, show_all_explicit = alle_param == "1", alle_param
    else:
        show_all, show_all_explicit = tab == "alle", None

    channel_filter = query_params.get("channel") or None
    if channel_filter not in CHANNEL_LABELS:
        channel_filter = None
    bundesland_filter = query_params.get("bundesland") or None
    if bundesland_filter not in GERMAN_STATES:
        bundesland_filter = None
    ampel_filter = query_params.get("ampel") or None
    if ampel_filter not in _AMPEL_FARBEN:
        ampel_filter = None
    # ort/status/zugewiesen: keine feste Werteliste zum Validieren gegen -
    # Ort und Zugewiesen sind Freitext, und für Status extra eine Kopie der
    # CHECK-Constraint zu pflegen wäre genau das Muster, das erst kürzlich
    # zum 'simuliert'-Fund geführt hat (s. docs/FUNDE.md). Ein nicht
    # passender Wert liefert schlicht null Treffer, kein Fehler.
    ort_filter = (query_params.get("ort") or "").strip() or None
    status_filter = (query_params.get("status") or "").strip() or None
    zugewiesen_filter = (query_params.get("zugewiesen") or "").strip() or None

    return {
        "tab": tab,
        "show_all": show_all,
        "show_all_explicit": show_all_explicit,
        "search": (query_params.get("q") or "").strip() or None,
        "sort_mode": sort_mode,
        "sort_explicit": sort_explicit,
        "channel_filter": channel_filter,
        "bundesland_filter": bundesland_filter,
        "ampel_filter": ampel_filter,
        "ort_filter": ort_filter,
        "status_filter": status_filter,
        "zugewiesen_filter": zugewiesen_filter,
    }


@router.get("")
def dashboard(request: Request):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    p = _resolve_dashboard_params(request.query_params)
    _fetch_only = {k: v for k, v in p.items() if k not in ("sort_explicit", "show_all_explicit")}

    with get_connection() as conn:
        rows = _fetch_leads(conn, **_fetch_only)
        positions = _fetch_vorgang_positions(conn, [r["lead_nummer"] for r in rows if r["lead_nummer"] is not None])
        leads = [_decorate_row_safe(row, positions.get(str(row["id"]))) for row in rows]
        filter_options = _fetch_filter_options(conn)
        wartende_leads = count_wartende_leads(conn)
        leads_im_korrekturfenster = count_leads_im_korrekturfenster(conn)

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
        "sort_mode": p["sort_mode"],
        "channel_filter": p["channel_filter"] or "",
        "bundesland_filter": p["bundesland_filter"] or "",
        "ampel_filter": p["ampel_filter"] or "",
        "ort_filter": p["ort_filter"] or "",
        "status_filter": p["status_filter"] or "",
        "zugewiesen_filter": p["zugewiesen_filter"] or "",
        "filter_options": filter_options,
        "ampel_optionen": [(f, _AMPEL_FARBE_LABELS_FILTER[f]) for f in _AMPEL_FARBEN],
        "ampel_labels": _AMPEL_FARBE_LABELS_FILTER,
        "alle_toggle_url": url(show_all_explicit="0" if p["show_all"] else "1"),
        "sort_url_aeltest": url(sort_explicit="aeltest"),
        "sort_url_neueste": url(sort_explicit="neueste"),
        "sort_url_nummer_auf": url(sort_explicit="nummer_auf"),
        "sort_url_nummer_ab": url(sort_explicit="nummer_ab"),
        "clear_filters_url": url(
            search=None, channel_filter=None, bundesland_filter=None,
            ampel_filter=None, ort_filter=None, status_filter=None, zugewiesen_filter=None,
        ),
        "csv_export_url": url(path="/admin/export.csv"),
        "channel_labels": CHANNEL_LABELS,
        "status_label": status_label,
        # Inline-Bearbeitung Status/Zugewiesen direkt in der Liste (Punkt 2,
        # Marco 2026-08-18): Options-Liste fürs <select>, plus die reine
        # Werteliste zum Prüfen, ob eine Zeile überhaupt inline editierbar
        # ist (nur die 5 manuell setzbaren Status - duplikat/ersetzt/ausland
        # bleiben wie bisher nur über die Detailansicht änderbar, s.
        # _MANUALLY_SETTABLE_STATUSES oben).
        "status_optionen": [(value, status_label(value)) for value in _MANUALLY_SETTABLE_STATUSES],
        "editierbare_status": _MANUALLY_SETTABLE_STATUSES,
        "wartende_leads": wartende_leads,
        "leads_im_korrekturfenster": leads_im_korrekturfenster,
    }
    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context=context)


def _dashboard_url(
    *,
    tab: str,
    show_all_explicit: str | None,
    search: str | None,
    sort_explicit: str | None,
    channel_filter: str | None = None,
    bundesland_filter: str | None = None,
    ampel_filter: str | None = None,
    ort_filter: str | None = None,
    status_filter: str | None = None,
    zugewiesen_filter: str | None = None,
    path: str = "/admin",
    **_ignored,  # sort_mode/show_all u.ä. aus p durchgereicht, hier irrelevant
) -> str:
    params: list[tuple[str, str]] = [("tab", tab)]
    if show_all_explicit is not None:
        # "0"/"1" statt nur bei True zu setzen - im Tab "Alle" muss sich
        # auch ein explizites Ausblenden (Default dort ist "an") in der URL
        # ausdrücken lassen, nicht nur ein Einblenden.
        params.append(("alle", show_all_explicit))
    if sort_explicit:
        params.append(("sort", sort_explicit))
    if search:
        params.append(("q", search))
    if channel_filter:
        params.append(("channel", channel_filter))
    if bundesland_filter:
        params.append(("bundesland", bundesland_filter))
    if ampel_filter:
        params.append(("ampel", ampel_filter))
    if ort_filter:
        params.append(("ort", ort_filter))
    if status_filter:
        params.append(("status", status_filter))
    if zugewiesen_filter:
        params.append(("zugewiesen", zugewiesen_filter))
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
    sort_mode: str,
    channel_filter: str | None = None,
    bundesland_filter: str | None = None,
    ampel_filter: str | None = None,
    ort_filter: str | None = None,
    status_filter: str | None = None,
    zugewiesen_filter: str | None = None,
    only_id: str | None = None,
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

    if ampel_filter == "defekt":
        # 'defekt' wird nie in traffic_light gespeichert (Python-only
        # Fallback für eine gescheiterte Aufbereitung, s. _defekte_zeile) -
        # das tatsächliche Signal dafür ist eine fehlende Ampel: entweder
        # noch nie berechnet, oder ein Schreibpfad hat apply_traffic_light
        # vergessen (genau das Muster, das Block c verhindern soll).
        conditions.append("l.traffic_light IS NULL")
    elif ampel_filter:
        conditions.append("l.traffic_light = %(ampel_filter)s")
        params["ampel_filter"] = ampel_filter

    if ort_filter:
        conditions.append("l.city = %(ort_filter)s")
        params["ort_filter"] = ort_filter

    if status_filter:
        conditions.append("l.status = %(status_filter)s")
        params["status_filter"] = status_filter

    if zugewiesen_filter:
        conditions.append("l.assigned_to = %(zugewiesen_filter)s")
        params["zugewiesen_filter"] = zugewiesen_filter

    if only_id:
        # Schnellbearbeitung (Punkt 2): dieselbe WHERE-Logik wie die Liste,
        # nur auf einen einzelnen Lead eingeschränkt - damit lässt sich ohne
        # eine zweite Filter-Nachbildung prüfen, ob eine gerade geänderte
        # Zeile noch zum aktiven Filter passt (leeres Ergebnis = nein).
        conditions.append("l.id = %(only_id)s")
        params["only_id"] = only_id

    where_sql = " AND ".join(conditions) if conditions else "true"
    order_sql = _SORT_MODE_SQL[sort_mode]

    # Alle interpolierten SQL-Fragmente oben stammen aus fest codierten
    # Strings (Tab-/Sort-Auswahl per Dictionary-Lookup) - Nutzereingaben
    # (search, Status-Listen, Filterwerte) laufen ausschließlich über
    # %()s-Parameter.
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                l.id, l.lead_nummer, l.created_at, l.name, l.name_raw, l.city, l.geo_state, l.geo_country,
                l.lat, l.lon,
                l.channel, l.channel_source, l.heard_about, l.status, l.assigned_to,
                l.is_spam, l.spam_reason, l.in_service_area, l.geocode_status,
                l.phone_raw, l.phone_valid, l.postal_code, l.street,
                l.email, l.is_owner, l.contact_time_preference, l.message,
                l.contacted_at, l.disqualify_reason, l.privacy_accepted_at,
                l.duplicate_of, l.superseded_by, l.traffic_light, l.traffic_light_reason,
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


# Spalte -> Anzeigename für die Spaltenfilter-Header (Marco, 2026-08-17,
# ersetzt die zwei Dropdowns über der Liste). Ampel bewusst nicht dabei -
# s. _AMPEL_FARBEN oben, keine echte Spalte.
_SPALTENFILTER: dict[str, str] = {
    "ort_filter": "city",
    "bundesland_filter": "geo_state",
    "channel_filter": "channel",
    "status_filter": "status",
    "zugewiesen_filter": "assigned_to",
}


def _distinct_values(conn: psycopg.Connection, column: str) -> list[str]:
    # column kommt ausschließlich aus _SPALTENFILTER oben (feste, im Code
    # stehende Werte) - f-String-Interpolation des Spaltennamens ist damit
    # unproblematisch, wie an anderen Stellen in dieser Datei.
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {column} FROM leads WHERE {column} IS NOT NULL ORDER BY {column}")
        return [r[0] for r in cur.fetchall()]


def _fetch_filter_options(conn: psycopg.Connection) -> dict[str, list[str]]:
    """Optionen für die sechs Spaltenfilter, aus den tatsächlich
    vorhandenen Werten (Marco, 2026-08-17: "kommt aktuell nicht vor" soll
    nicht mit "gibt es nicht" verwechselt werden) - global über alle Leads,
    nicht auf den aktuellen Tab/andere Filter eingeschränkt, damit sich die
    Optionen nicht kaskadierend verändern, während man filtert."""
    return {param: _distinct_values(conn, column) for param, column in _SPALTENFILTER.items()}


# Status-Werte, die keine eigenständig zu bearbeitende Anfrage sind, sondern
# ein technisches/historisches Artefakt (Konzept §4/§J) - Zeile in der Liste
# gedämpft dargestellt statt gleichrangig neben aktiven Leads zu stehen
# (Marco, 2026-08-16: "man muss die Logik erraten, statt sie zu sehen").
_INAKTIVE_STATUSWERTE = {"duplikat", "ersetzt", "spam", "ausland"}


def _fetch_vorgang_positions(conn: psycopg.Connection, lead_nummern: list[int]) -> dict[str, tuple[int, int]]:
    """id (str) -> (Position, Gesamtgröße) innerhalb desselben Vorgangs
    (lead_nummer) - über ALLE Zeilen mit dieser Nummer hinweg, unabhängig
    von Tab/Filter/Suche der aktuellen Ansicht. Absichtlich NICHT aus der
    gefilterten Haupt-Query abgeleitet (z.B. per Fenster-Funktion dort):
    ein gefilterter Tab würde sonst eine falsch kleine Gruppengröße zeigen
    - "Version 1 von 1" für eine Zeile, die tatsächlich Teil einer
    3-zeiligen Korrekturkette ist, nur weil die anderen zwei Zeilen im
    aktuellen Tab ausgeblendet sind. Ersetzt _kette_info/_duplikatgruppe_info
    (Marco, 2026-08-17: Zugehörigkeit über die Lead-Nummer statt über einen
    Hinweis-Satz) - lead_nummer vereint ohnehin schon beide Kantentypen
    (duplicate_of UND superseded_by, s. scripts/backfill_lead_nummer.py),
    eine auf nur EINER Kantenart basierende Positionsangabe wäre für einen
    gemischten Cluster unvollständig gewesen."""
    if not lead_nummern:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id,
                   row_number() OVER (PARTITION BY lead_nummer ORDER BY created_at ASC) AS position,
                   count(*) OVER (PARTITION BY lead_nummer) AS gesamt
            FROM leads
            WHERE lead_nummer = ANY(%(nummern)s)
            """,
            {"nummern": lead_nummern},
        )
        rows = cur.fetchall()
    return {str(r["id"]): (r["position"], r["gesamt"]) for r in rows}


def _decorate_row(row: dict, vorgang_position: tuple[int, int] | None) -> dict:
    # Block c: traffic_light/traffic_light_reason werden bei jedem
    # Schreibvorgang berechnet (app/traffic_light.py), hier nur noch
    # gelesen statt bei jedem Aufruf neu über ampel() berechnet. Fehlt der
    # Wert (sollte nach Block c nie mehr vorkommen), wird das laut
    # geworfen statt geraten - _decorate_row_safe() fängt das ab und zeigt
    # die Zeile als "defekt" statt sie stillschweigend falsch/leer
    # darzustellen (dasselbe Prinzip wie beim geocode_status='simuliert'-
    # Fund, s. docs/FUNDE.md: ein vergessener Schreibpfad muss sichtbar
    # werden, nicht in einer Live-Neuberechnung verschwinden).
    if row["traffic_light"] is None:
        raise ValueError(f"traffic_light fehlt für Lead {row['id']} - ein Schreibpfad hat sie nicht aktualisiert")

    status_display = status_label(row["status"])
    # vorgang_hinweis getrennt von status_display gehalten (Punkt 2, Marco
    # 2026-08-18): die Inline-Bearbeitung in der Liste ersetzt status_display
    # durch ein <select>, das "Version X von Y" nicht mit anzeigen kann -
    # das Template rendert vorgang_hinweis deshalb als eigene Zeile darunter.
    # status_display bleibt unverändert (CSV-Export/andere Konsumenten lesen
    # weiter dieses eine kombinierte Feld).
    vorgang_hinweis = None
    if vorgang_position and vorgang_position[1] > 1:
        # Zugehörigkeit über die Lead-Nummer sichtbar machen, nicht über
        # einen zusätzlichen Hinweis-Satz (Marco, 2026-08-17: "Teil einer
        # Korrekturkette" ist zu textlastig). Nur bei > 1 Zeile im Vorgang -
        # für den Normalfall (keine Korrektur/kein Duplikat) wäre "Version
        # 1 von 1" reine Auffüllung ohne Information.
        pos, gesamt = vorgang_position
        vorgang_hinweis = f"Version {pos} von {gesamt}"
        status_display = f"{status_display}, {vorgang_hinweis}"

    badges: list[dict] = []

    if row["erneut_angefragt_am"] is not None:
        badges.append({"text": f"Erneut angefragt am {format_berlin_datetime(row['erneut_angefragt_am'])}", "url": None})
    if row["duplicate_of"] and row["duplicate_of_created_at"] is not None:
        badges.append({
            "text": f"Duplikat von Anfrage vom {format_berlin_datetime(row['duplicate_of_created_at'])}",
            "url": f"/admin/leads/{row['duplicate_of']}",
        })
    if row["superseded_by"] and row["superseded_by_created_at"] is not None:
        # Diese Zeile ist die ALTE Seite der Kette (row_inaktiv=True) - der
        # Text beginnt bewusst mit dem Status DIESER Zeile ("Veraltet"),
        # nicht nur mit dem Verweisziel, damit die Richtung am Text selbst
        # ablesbar ist und nicht nur über die Dämpfung/den Kontext erschlossen
        # werden muss (Marco, TODO Punkt 2: beide alten Texte zeigten
        # aufeinander, ohne dass am Text erkennbar war, welche Seite gilt).
        badges.append({
            "text": f"Veraltet – aktuelle Version vom {format_berlin_datetime(row['superseded_by_created_at'])}",
            "url": f"/admin/leads/{row['superseded_by']}",
        })
    if row["vorgaenger_id"] and row["vorgaenger_created_at"] is not None:
        # Spiegelbildlich: diese Zeile ist die GÜLTIGE Seite, Text beginnt
        # entsprechend mit "Aktuelle Version".
        badges.append({
            "text": f"Aktuelle Version – frühere Anfrage vom {format_berlin_datetime(row['vorgaenger_created_at'])}",
            "url": f"/admin/leads/{row['vorgaenger_id']}",
        })
    if row["kontakt_bekannt"]:
        badges.append({"text": "Kontakt bekannt", "url": None})
    if row["phone_raw"] and not row["phone_valid"]:
        badges.append({"text": "Telefon prüfen", "url": None})
    if row["geocode_status"] == "mehrdeutig":
        badges.append({"text": "Adresse mehrdeutig", "url": None})

    # Maps-Link auch in der Liste (Marco, TODO Punkt 3) - identische Regel
    # wie in der Detailansicht (_field_groups): nur bei vorhandenen
    # Koordinaten, sonst None statt einer Platzhalter-Andeutung. Das Template
    # blendet die Stelle in der Ort-Spalte dann komplett aus.
    maps_link = None
    if row["lat"] is not None and row["lon"] is not None:
        maps_link = f"https://maps.google.com/?q={row['lat']},{row['lon']}"

    # Adresse als eine Spalte statt Straße/PLZ/Ort einzeln (Marco,
    # 2026-08-18: "In der Liste fehlt die Adresszeile") - dieselbe
    # Formatierung wie in der Bestätigungsmail (app/core/display.py::
    # format_address), damit beide Stellen nie auseinanderlaufen.
    # Bundesland bleibt eine eigene Spalte (wird gefiltert).
    address_display = format_address(row["street"], row["postal_code"], row["city"])

    return {
        **row,
        "created_at_display": format_berlin_datetime(row["created_at"]),
        "status_display": status_display,
        "vorgang_hinweis": vorgang_hinweis,
        "address_display": address_display,
        "ampel_farbe": row["traffic_light"],
        "ampel_grund": row["traffic_light_reason"],
        "badges": badges,
        "maps_link": maps_link,
        "row_inaktiv": row["status"] in _INAKTIVE_STATUSWERTE,
        "zeile_defekt": False,
    }


def _defekte_zeile(row: dict) -> dict:
    """Fallback, wenn _decorate_row() für eine einzelne Zeile scheitert -
    Konzept: eine defekte Zeile erscheint MARKIERT als defekt, statt die
    ganze Liste mit abzureißen (Marco, 2026-08-17, Fund s. docs/FUNDE.md:
    ein einziger Lead mit geocode_status='simuliert' brachte vorher das
    komplette Dashboard zum Absturz, weil ampel() ungeschützt in der
    Schleife über alle Zeilen aufgerufen wurde - die richtige Stelle für
    diese Absicherung ist hier, pro Zeile, nicht eine Ebene höher).
    Vermeidet jede Funktion, die selbst werfen könnte (auch
    format_berlin_datetime setzt tzinfo voraus) - dieser Pfad muss unter
    allen Umständen durchlaufen."""
    return {
        **row,
        "created_at_display": str(row.get("created_at", "")),
        "status_display": "Fehler bei der Anzeige",
        "vorgang_hinweis": None,
        "ampel_farbe": "defekt",
        "ampel_grund": "Diese Zeile konnte nicht korrekt angezeigt werden - Details im Server-Log.",
        "badges": [],
        "maps_link": None,
        "address_display": str(row.get("street", "")),
        "row_inaktiv": False,
        "zeile_defekt": True,
    }


def _decorate_row_safe(row: dict, vorgang_position: tuple[int, int] | None) -> dict:
    try:
        return _decorate_row(row, vorgang_position)
    except Exception:
        logger.exception("Zeile konnte nicht aufbereitet werden (Lead %s)", row.get("id"))
        return _defekte_zeile(row)


# --- CSV-Export (Konzept §6/§8 K8, CLAUDE.md Regel 8) ---------------------
# Läuft über dieselben _fetch_leads()/_decorate_row() wie die Liste, damit
# Filter/Suche/Sortierung zwischen Ansicht und Export nie auseinanderlaufen
# können (Marco, 2026-08-16: "berücksichtigt den aktuell aktiven Filter und
# die Suche, nicht immer alles").

_AMPEL_FARBE_LABELS = {
    "gruen": "Grün", "gelb": "Gelb", "rot": "Rot", "grau": "Grau", "schwarz": "Schwarz",
    "defekt": "Fehler (Anzeige defekt)",
}

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

    p = _resolve_dashboard_params(request.query_params)

    with get_connection() as conn:
        rows = _fetch_leads(conn, **{k: v for k, v in p.items() if k not in ("sort_explicit", "show_all_explicit")})
        positions = _fetch_vorgang_positions(conn, [r["lead_nummer"] for r in rows if r["lead_nummer"] is not None])
        leads = [_decorate_row_safe(row, positions.get(str(row["id"]))) for row in rows]

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
        ampel_filter=p["ampel_filter"], ort_filter=p["ort_filter"],
        status_filter=p["status_filter"], zugewiesen_filter=p["zugewiesen_filter"],
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
    ampel_filter: str | None = None,
    ort_filter: str | None = None,
    status_filter: str | None = None,
    zugewiesen_filter: str | None = None,
) -> str:
    """Dateiname enthält Filter+Suche+Datum, damit mehrere Exporte am
    selben Tag nicht denselben Namen tragen und sich der Browser nicht
    stillschweigend für eine "(1)"-Kopie entscheidet (Marco, 2026-08-16)."""
    parts = ["standort-check-leads", tab]
    if show_all:
        parts.append("inkl-inaktive")
    if ort_filter:
        parts.append(f"ort-{_FILENAME_UNSAFE_RE.sub('-', ort_filter).strip('-').lower()}")
    if channel_filter:
        parts.append(f"kanal-{_FILENAME_UNSAFE_RE.sub('-', channel_filter).strip('-').lower()}")
    if bundesland_filter:
        parts.append(f"bundesland-{_FILENAME_UNSAFE_RE.sub('-', bundesland_filter).strip('-').lower()}")
    if ampel_filter:
        parts.append(f"ampel-{ampel_filter}")
    if status_filter:
        parts.append(f"status-{_FILENAME_UNSAFE_RE.sub('-', status_filter).strip('-').lower()}")
    if zugewiesen_filter:
        parts.append(f"zugewiesen-{_FILENAME_UNSAFE_RE.sub('-', zugewiesen_filter).strip('-').lower()}")
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
    context["ergebnis"] = request.query_params.get("ergebnis")
    context["status_label"] = status_label
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


def _geocode_candidates_for_display(row: dict) -> list[dict] | None:
    """Kandidaten mit Bundesland/Gemeinde für die Detailansicht (Block d) -
    nur bei geocode_status='mehrdeutig' und nur, wenn geocode_raw die
    rohen Nominatim-Ergebnisse enthält (ältere/simulierte/fehlgeschlagene
    Zeilen haben das nicht). None statt leerer Liste, wenn es nichts zu
    zeigen gibt - das Template unterscheidet damit "keine Kandidaten-
    Sektion nötig" von "Sektion da, aber zufällig leer"."""
    if row["geocode_status"] != "mehrdeutig":
        return None
    raw = row["geocode_raw"]
    if not raw or not raw.get("results"):
        return None
    return candidate_summaries(raw["results"])


def _maps_link_html(lat, lon) -> str:
    """Echter, klickbarer Link (Nebenfund: das Feld zeigte bisher nur die
    rohe URL als Text, ohne <a>-Tag) - dieselbe Behandlung wie das
    Maps-Symbol in der Liste (neuer Tab, noopener/noreferrer). lat/lon
    kommen aus der numeric-Spalte in der DB, nie aus direkt interpoliertem
    Nutzertext - Markup.format() escaped den Wert trotzdem zusätzlich, statt
    sich allein darauf zu verlassen."""
    if lat is None or lon is None:
        return "– (noch nicht geokodiert)"
    url = f"https://maps.google.com/?q={lat},{lon}"
    return Markup('<a href="{}" target="_blank" rel="noopener noreferrer">📍 Auf Google Maps öffnen</a>').format(url)


def _field_groups(row: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    """Alle Lead-Spalten außer message/duplicate_of/superseded_by/
    traffic_light(_reason)/status/assigned_to/disqualify_reason/
    contacted_at - message steht prominent oben, duplicate_of/superseded_by
    als Banner, traffic_light/traffic_light_reason stehen eigens oben in der
    Kopfzeile (ampel_farbe/ampel_grund im Kontext, s. _build_detail_context)
    statt hier nochmal in der Feldliste, und die Bearbeitungsfelder stehen
    als eigenes editierbares Formular (Aktionen) statt in dieser reinen
    Anzeige-Liste. "Alle Felder, auch leere" (Marco, 2026-08-16): jede
    Zeile erscheint immer, mit "–" statt Auslassung wenn leer."""
    name_value = row["name"] or "–"
    if row["name_normalized"] and row["name_raw"]:
        name_value += f" (wie eingegeben: {row['name_raw']})"

    email_value = row["email"]
    if row["email_normalized"] and row["email_normalized"] != row["email"]:
        email_value += f" (normalisiert: {row['email_normalized']})"

    email_mx_value = (
        "MX-Eintrag bestätigt (Domain nimmt Mail an)"
        if row["email_mx_status"] == "geprueft"
        else "Nicht prüfbar (DNS-Dienst war nicht erreichbar/Timeout - Adresse trotzdem angenommen)"
    )

    if row["phone_raw"]:
        if row["phone_valid"] and row["phone_e164"]:
            phone_value = f"{row['phone_raw']} (gültig, E.164: {row['phone_e164']})"
        else:
            phone_value = f"{row['phone_raw']} (nicht als gültige Nummer erkannt)"
    else:
        phone_value = "–"

    maps_link = _maps_link_html(row["lat"], row["lon"])

    koordinaten = f"{row['lat']}, {row['lon']}" if row["lat"] is not None else "–"

    return [
        ("Kontakt", [
            ("Name", name_value),
            ("E-Mail", email_value),
            ("E-Mail-Zustellbarkeit", email_mx_value),
            ("Telefon", phone_value),
        ]),
        ("Adresse (Grundstück)", [
            ("Straße", _text(row["street"])),
            ("PLZ (eingegeben)", _text(row["postal_code"])),
            ("PLZ (von Nominatim gefunden)", _text(row["geo_postal_code"])),
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
            ("Marketing-Opt-in (neue Angebote/Entwicklungen)", _ja_nein(row["marketing_opt_in"])),
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


# Feld-Diff bei F3-Korrekturen (Marco, 2026-08-18: "Der Feld-Diff liegt
# bereits im Event ersetzt" - app.core.merge.merge_fields() schreibt
# changed_fields/merged_fields mit den internen Feldnamen aus
# _merge_with_candidate() in app/submission.py, hier nur für die Anzeige
# auf deutsche Beschriftungen abgebildet). Nur in der Detailansicht (nicht
# in der Liste - würde dort keinen Platz haben und ist kein
# Listen-Anwendungsfall).
_MERGE_FELD_LABELS: dict[str, str] = {
    "name_raw": "Name",
    "email": "E-Mail",
    "phone_raw": "Telefon",
    "street": "Straße",
    "postal_code": "PLZ",
    "city": "Ort",
    "is_owner": "Eigentümer",
    "contact_time_preference": "Erreichbarkeit",
    "message": "Anmerkung",
    "heard_about": "Wie gefunden",
}


def _diff_wert_text(value) -> str:
    if isinstance(value, bool):
        return _ja_nein(value)
    return _text(value)


def _ersetzt_diff(payload: dict) -> dict:
    changed = payload.get("changed_fields") or {}
    merged = payload.get("merged_fields") or {}
    return {
        "changed": [
            {
                "label": _MERGE_FELD_LABELS.get(feld, feld),
                "alt": _diff_wert_text(werte.get("alt")),
                "neu": _diff_wert_text(werte.get("neu")),
            }
            for feld, werte in changed.items()
        ],
        "merged": [
            {"label": _MERGE_FELD_LABELS.get(feld, feld), "wert": _diff_wert_text(wert)}
            for feld, wert in merged.items()
        ],
    }


# Mail-Status deutlich sichtbar machen (Marco, 2026-08-18: "aktuell sieht
# es aus, als müsste man manuell versenden" - der Button "Bestätigungsmail
# erneut senden" stand ohne erkennbaren Grund daneben). Die Daten standen
# schon in email_status/email_attempts/email_last_error/email_sent_at
# (Spalten) bzw. in den mail_gesendet/mail_fehlgeschlagen-Events - hier nur
# zu einem einzigen, klaren Satz + Ampelfarbe zusammengefasst, direkt über
# dem Button statt in der allgemeinen Feldliste weiter unten.
_MAIL_STATUS_FARBEN: dict[str, str] = {
    "gesendet": "gruen",
    "fehlgeschlagen": "rot",
    "offen": "grau",
    "simuliert": "grau",
    "uebersprungen": "schwarz",
}


def _mail_status_hinweis(row: dict, events: list[dict]) -> dict:
    status = row["email_status"]
    letztes_mail_event = next(
        (
            e for e in reversed(events)
            if str(e["lead_id"]) == str(row["id"]) and e["event_type"] in ("mail_gesendet", "mail_fehlgeschlagen")
        ),
        None,
    )
    zeitpunkt = None
    if row["email_sent_at"] is not None:
        zeitpunkt = format_berlin_datetime(row["email_sent_at"])
    elif letztes_mail_event is not None:
        zeitpunkt = format_berlin_datetime(letztes_mail_event["created_at"])

    if status == "gesendet":
        text = f"Gesendet am {zeitpunkt}." if zeitpunkt else "Gesendet."
    elif status == "fehlgeschlagen":
        fehler = row["email_last_error"] or "unbekannter Fehler"
        text = f"Fehlgeschlagen{' am ' + zeitpunkt if zeitpunkt else ''} — {fehler}"
    elif status == "offen":
        text = "Ausstehend — noch nicht versendet (nächster automatischer Retry oder manuell über den Button unten)."
    elif status == "simuliert":
        text = f"Simuliert{' am ' + zeitpunkt if zeitpunkt else ''} (Testmodus DRY_RUN_EMAIL, kein echter Versand)."
    elif status == "uebersprungen":
        text = "Übersprungen (Spamverdacht) — bewusst kein Versand."
    else:
        text = status_label(status)

    return {"text": text, "farbe": _MAIL_STATUS_FARBEN.get(status, "grau"), "versuche": row["email_attempts"]}


def _build_detail_context(
    row: dict,
    ancestors: list[dict],
    events: list[dict],
    duplicate_of_row: dict | None,
    superseded_by_row: dict | None,
) -> dict:
    # Block c: wie _decorate_row() - lesen statt live neu berechnen.
    # Fehlender Wert wird hier NICHT abgefangen (anders als in der Liste):
    # eine einzelne Detailansicht darf im Fehlerfall ruhig mit einem
    # geloggten 500er scheitern, das reißt keine anderen Zeilen mit (der
    # Grund, warum die Isolierung aus Punkt 1 speziell für die LISTE nötig
    # war, s. docs/FUNDE.md).
    if row["traffic_light"] is None:
        raise ValueError(f"traffic_light fehlt für Lead {row['id']} - ein Schreibpfad hat sie nicht aktualisiert")

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
            "diff": _ersetzt_diff(e["payload"]) if e["event_type"] == "ersetzt" and e["payload"] else None,
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
        "mail_status_hinweis": _mail_status_hinweis(row, events),
        "ampel_farbe": row["traffic_light"],
        "ampel_grund": row["traffic_light_reason"],
        "message": row["message"],
        "field_groups": _field_groups(row),
        "geocode_candidates": _geocode_candidates_for_display(row),
        "ancestors": ancestors_display,
        "events": events_display,
        "duplicate_of_row": duplicate_of_row,
        "superseded_by_row": superseded_by_row,
        "manually_settable_statuses": [(value, status_label(value)) for value in _MANUALLY_SETTABLE_STATUSES],
    }


# --- Aktionen (Konzept §6) -------------------------------------------------


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

    # Marco, 2026-08-18: "Beim Setzen von disqualifiziert soll der Grund
    # abgefragt werden" - serverseitig erzwungen (CLAUDE.md Regel 11:
    # clientseitige Prüfungen sind Komfort, nie Sicherheit), nicht nur über
    # das Formularfeld nahegelegt. Das Feld selbst bleibt immer sichtbar
    # (auch für andere Status), nur bei status='disqualifiziert' wird ein
    # gefüllter Wert verlangt.
    if status == "disqualifiziert" and not disqualify_reason:
        raise HTTPException(status_code=400, detail="Für Status 'Disqualifiziert' wird ein Grund benötigt.")

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
            # Block c: is_spam/spam_reason können sich hier geändert haben
            # (manueller Statuswechsel ODER Spam-Freigabe/-Markierung,
            # Konzept §J) - unbedingt statt nur bei is_spam/spam_reason in
            # updates, damit ein künftig neu hinzugefügtes ampel-relevantes
            # Feld hier nicht separat vergessen werden kann.
            apply_traffic_light(conn, lead_id)

    return RedirectResponse(url=f"/admin/leads/{lead_id}?aktion=gespeichert", status_code=303)


# --- Schnellbearbeitung in der Liste (Punkt 2, Marco 2026-08-18) ----------
# Sales arbeitet die Liste morgens von oben nach unten telefonierend ab -
# jeden Lead einzeln öffnen, Status ändern, zurücknavigieren wäre Reibung im
# Hauptarbeitsablauf. Deckt bewusst nur Status + Zugewiesen ab (die zwei
# Felder für diesen Workflow), nicht disqualify_reason (Freitext, bleibt
# Detailansicht) und nicht die drei automatisch gesetzten Status duplikat/
# ersetzt/ausland (dieselbe Einschränkung wie beim bestehenden Dropdown in
# der Detailansicht, s. _MANUALLY_SETTABLE_STATUSES). JSON statt Redirect,
# weil das Dashboard per fetch() im Hintergrund speichert (kein Neuladen,
# Liste bleibt an Ort und Stelle mit denselben Filtern) - dasselbe Muster
# wie der bestehende globale Retry-Button.


@router.post("/leads/{lead_id}/schnellbearbeitung")
def quick_update_lead(
    request: Request,
    lead_id: str,
    status: str = Form(...),
    assigned_to: str = Form(""),
    view: str = Form(""),
    disqualify_reason: str | None = Form(None),
):
    admin_username = _current_admin(request)
    if not admin_username:
        # Kein Redirect wie bei den Formular-Aktionen: der Aufrufer ist
        # fetch(), ein 401 mit JSON lässt sich dort sauber behandeln, ein
        # Redirect auf /admin/login würde als "Erfolg" mit HTML-Inhalt
        # ankommen und die spätere JSON-Auswertung zum Absturz bringen.
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    if status not in _MANUALLY_SETTABLE_STATUSES:
        raise HTTPException(status_code=400, detail="Ungültiger Status.")

    assigned_to = assigned_to.strip() or None
    # None (Feld gar nicht mitgeschickt, s. Dashboard-JS) heißt "unverändert
    # lassen" - anders als bei assigned_to/status kann die Schnellbearbeitung
    # den Grund nicht einfach immer mitschicken, weil er nur bei einem
    # Wechsel AUF 'disqualifiziert' abgefragt wird (Prompt im Dashboard-JS).
    disqualify_reason = disqualify_reason.strip() if disqualify_reason is not None else None

    with get_connection() as conn:
        row = _fetch_lead(conn, lead_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Lead nicht gefunden.")

        # Wie update_lead_bearbeitung: 'disqualifiziert' braucht einen Grund
        # (Marco, 2026-08-18), serverseitig geprüft (CLAUDE.md Regel 11) statt
        # sich auf den Prompt im Dashboard-JS zu verlassen. Fällt auf den
        # bereits gespeicherten Grund zurück, wenn dieser Aufruf gar keinen
        # neuen mitschickt (z.B. eine reine Zugewiesen-Änderung an einem
        # bereits disqualifizierten Lead darf nicht plötzlich verlangen, den
        # Grund erneut einzutippen).
        finaler_grund = disqualify_reason if disqualify_reason is not None else row["disqualify_reason"]
        if status == "disqualifiziert" and not finaler_grund:
            raise HTTPException(status_code=400, detail="Für Status 'Disqualifiziert' wird ein Grund benötigt.")

        if row["status"] in _INAKTIVE_STATUSWERTE and row["status"] != "spam":
            # Serverseitiges Sicherheitsnetz, nicht nur im Template
            # versteckt (CLAUDE.md Regel 11): ein direkter POST an diesen
            # Endpunkt darf eine duplikat/ersetzt/ausland-Zeile nicht über
            # die Schnellbearbeitung umbiegen - das würde die Relation
            # (duplicate_of/superseded_by) stehen lassen, aber den Status
            # so setzen, als gäbe es sie nicht. 'spam' ist ausgenommen: das
            # ist der einzige der vier gedämpften Status, der laut Konzept
            # §J manuell zurückgesetzt werden können muss.
            raise HTTPException(status_code=409, detail="Dieser Status ist nur über die Detailansicht änderbar.")

        updates: dict = {}

        if status != row["status"]:
            updates["status"] = status
            insert_event(conn, lead_id, "status_geaendert", {"von": row["status"], "nach": status})

        # Identische Logik wie update_lead_bearbeitung oben (is_spam-Sync,
        # contacted_at) - absichtlich dupliziert statt in eine gemeinsame
        # Funktion gezogen, weil die beiden Endpunkte unterschiedlich auf
        # Fehler/Ergebnis reagieren (Redirect+Flash vs. JSON) und eine
        # gemeinsame Funktion an dieser Stelle mehr Kopplung als Nutzen
        # gebracht hätte; beide Stellen sind kurz genug, um beim Ändern der
        # einen die andere nicht zu vergessen.
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

        if disqualify_reason is not None and disqualify_reason != (row["disqualify_reason"] or ""):
            updates["disqualify_reason"] = disqualify_reason or None

        if updates:
            _update_lead(conn, lead_id, updates)
            apply_traffic_light(conn, lead_id)

        # Vollständig aufbereitete Zeile für die Antwort - dieselbe
        # _fetch_leads()/_decorate_row()-Pipeline wie die Liste selbst
        # (tab='alle', show_all=True: hier zählt nur, was JETZT in der DB
        # steht, keine Filterbedingung), damit Ampel/Badges/Version-Hinweis
        # exakt so aufbereitet werden wie bei jedem normalen Seitenaufruf.
        aktuelle_zeile = _fetch_leads(conn, tab="alle", show_all=True, search=None, sort_mode="aeltest", only_id=lead_id)
        if not aktuelle_zeile:
            raise HTTPException(status_code=404, detail="Lead nicht gefunden.")
        raw = aktuelle_zeile[0]
        positions = _fetch_vorgang_positions(conn, [raw["lead_nummer"]] if raw["lead_nummer"] is not None else [])
        dekoriert = _decorate_row_safe(raw, positions.get(str(raw["id"])))

        # Passt die Zeile noch zum Filter, unter dem die Änderung ausgelöst
        # wurde? "view" ist der rohe Query-String der Liste zum Zeitpunkt
        # des Klicks (vom Dashboard-JS aus window.location.search
        # mitgeschickt) - dieselbe _resolve_dashboard_params()/_fetch_leads()
        # -Kette wie beim normalen Seitenaufruf, nur mit only_id
        # eingeschränkt, statt einer zweiten Nachbildung der Filterlogik.
        filter_params = _resolve_dashboard_params(QueryParams(view))
        filter_kwargs = {k: v for k, v in filter_params.items() if k not in ("sort_explicit", "show_all_explicit")}
        passt_zum_filter = bool(_fetch_leads(conn, only_id=lead_id, **filter_kwargs))

    return {
        "status": dekoriert["status"],
        "status_display": dekoriert["status_display"],
        "vorgang_hinweis": dekoriert["vorgang_hinweis"],
        "assigned_to": dekoriert["assigned_to"] or "",
        "ampel_farbe": dekoriert["ampel_farbe"],
        "ampel_grund": dekoriert["ampel_grund"],
        "row_inaktiv": dekoriert["row_inaktiv"],
        "passt_zum_filter": passt_zum_filter,
    }


def _versende_bestaetigungsmail(lead_id: str, base_url: str) -> str:
    """Holt den Lead frisch aus der DB und sendet die Bestätigungsmail
    erneut - gemeinsame Kernoperation für den redirect-basierten Button in
    der Detailansicht (resend_lead_mail) UND die fetch-basierte
    Zeilen-Schnellaktion in der Liste (quick_resend_mail). Nur Fehler-
    reaktion und Antwortformat unterscheiden sich zwischen den beiden
    Aufrufern (wie bei quick_update_lead vs. update_lead_bearbeitung),
    deshalb bleibt das dort getrennt, die eigentliche Arbeit hier gebündelt.
    Wirft ValueError, wenn der Lead nicht existiert."""
    with get_connection() as conn:
        row = _fetch_lead(conn, lead_id)
        if row is None:
            raise ValueError(f"Lead {lead_id} nicht gefunden.")
        data = row_to_new_lead_data(row)

    with get_connection() as conn:
        return send_confirmation_email(conn, lead_id, data, base_url, DedupCase.NEU)


@router.post("/leads/{lead_id}/mail-erneut-senden")
def resend_lead_mail(request: Request, lead_id: str):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    aktion = "mail_gesendet"
    try:
        _versende_bestaetigungsmail(lead_id, str(request.base_url))
    except ValueError:
        raise HTTPException(status_code=404, detail="Lead nicht gefunden.")
    except Exception:
        # Admin-Aktion, kein Submit-Pfad - CLAUDE.md Regel 2 gilt hier nicht
        # wörtlich, aber ein rohes 500 für einen Klick auf "erneut senden"
        # wäre trotzdem schlechtes Verhalten. send_confirmation_email fängt
        # Brevo-/Netzwerkfehler schon selbst ab; dieser Fang ist nur das
        # Netz für alles andere (z.B. DB-Fehler beim Status-Update).
        logger.exception("Manueller Mail-Resend fehlgeschlagen für Lead %s", lead_id)
        aktion = "mail_fehler"

    return RedirectResponse(url=f"/admin/leads/{lead_id}?aktion={aktion}", status_code=303)


@router.post("/leads/{lead_id}/geocoding-wiederholen")
def retry_lead_geocoding(request: Request, lead_id: str):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        ergebnis = retry_one_geocode(lead_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lead nicht gefunden.")
    except Exception:
        # Wie beim Mail-Resend: retry_one_geocode() fängt anzunehmende
        # Nominatim-/Netzwerkfehler schon selbst ab (landet dann auf
        # "fehlgeschlagen"), dieser Fang ist nur das Netz für alles andere.
        logger.exception("Manuelles Geocoding-Retry fehlgeschlagen für Lead %s", lead_id)
        ergebnis = "fehler"

    return RedirectResponse(url=f"/admin/leads/{lead_id}?aktion=geocoding&ergebnis={ergebnis}", status_code=303)


# --- Zeilen-Schnellaktionen in der Liste (Marco, 2026-08-19) ---------------
# Der globale Retry-Button (weiter unten, /admin/retry) respektiert
# process_after und tut bei frischen Leads deshalb bewusst nichts (Konzept
# §G) - für den Einzelfall (z.B. eine Demo, bei der ein frischer Lead sofort
# ein Ergebnis zeigen soll) braucht es einen Weg, der process_after bewusst
# übergeht, ohne auf die Detailansicht wechseln zu müssen. retry_one_geocode()
# tut das bereits (s. app/retry.py-Docstring); diese beiden Endpunkte sind
# fetch-basierte Geschwister von retry_lead_geocoding/resend_lead_mail oben -
# gleiche Kernoperation, JSON statt Redirect (wie schnellbearbeitung vs.
# bearbeitung).


@router.post("/leads/{lead_id}/geocoding-wiederholen-schnell")
def quick_retry_geocoding(request: Request, lead_id: str, view: str = Form("")):
    admin_username = _current_admin(request)
    if not admin_username:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    try:
        ergebnis = retry_one_geocode(lead_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lead nicht gefunden.")
    except Exception:
        logger.exception("Geocoding-Schnellaktion fehlgeschlagen für Lead %s", lead_id)
        ergebnis = "fehler"

    with get_connection() as conn:
        # Dieselbe _fetch_leads()/_decorate_row()-Pipeline wie die Liste
        # selbst (s. quick_update_lead oben) statt der schlankeren
        # _fetch_lead() - Geocoding kann geo_state/Ampel ändern, die beide
        # auch Filterkriterien der Liste sind (Bundesland-/Ampel-Filter),
        # nicht nur Anzeigewerte.
        zeilen = _fetch_leads(conn, tab="alle", show_all=True, search=None, sort_mode="aeltest", only_id=lead_id)
        if not zeilen:
            raise HTTPException(status_code=404, detail="Lead nicht gefunden.")
        raw = zeilen[0]
        positions = _fetch_vorgang_positions(conn, [raw["lead_nummer"]] if raw["lead_nummer"] is not None else [])
        dekoriert = _decorate_row_safe(raw, positions.get(str(raw["id"])))

        filter_params = _resolve_dashboard_params(QueryParams(view))
        filter_kwargs = {k: v for k, v in filter_params.items() if k not in ("sort_explicit", "show_all_explicit")}
        passt_zum_filter = bool(_fetch_leads(conn, only_id=lead_id, **filter_kwargs))

    return {
        "ergebnis": ergebnis,
        "ergebnis_label": status_label(ergebnis),
        "ampel_farbe": dekoriert["ampel_farbe"],
        "ampel_grund": dekoriert["ampel_grund"],
        "passt_zum_filter": passt_zum_filter,
    }


@router.post("/leads/{lead_id}/mail-erneut-senden-schnell")
def quick_resend_mail(request: Request, lead_id: str):
    admin_username = _current_admin(request)
    if not admin_username:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    try:
        email_status = _versende_bestaetigungsmail(lead_id, str(request.base_url))
    except ValueError:
        raise HTTPException(status_code=404, detail="Lead nicht gefunden.")
    except Exception:
        logger.exception("Mail-Schnellaktion fehlgeschlagen für Lead %s", lead_id)
        email_status = "fehlgeschlagen"

    return {"ergebnis": email_status, "ergebnis_label": status_label(email_status)}


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
        request.headers.get("X-Retry-Secret"), expected=get_env("RETRY_SECRET")
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

    zeilen = [_decorate_auswertung_row(r) for r in rows]
    gesamt_anfragen = sum(r["anfragen"] for r in zeilen)

    context = {
        "username": admin_username,
        "gruppierungen": _GRUPPIERUNGEN,
        "aktive_gruppierung": gruppierung,
        "zeilen": zeilen,
        "gesamt_anfragen": gesamt_anfragen,
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
