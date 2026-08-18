"""Systematischer Testlauf über die Randfälle aus Konzept + Aufgabe.

Läuft live gegen POST /submit (echter Server, s. --help) und liest das
Ergebnis direkt aus der Datenbank - kein Mock. Jeder Fall trägt eine vorher
festgelegte Erwartung; das Skript vergleicht nur, es repariert nichts.
Schreibt docs/TESTLAUF.md aus den gesammelten Ergebnissen und löscht am
Ende alle selbst angelegten Leads wieder (nur die exakt getrackten IDs,
kein Muster-Löschen).

Aufruf: zuerst `uvicorn app.main:app --port 8731` in einem zweiten
Terminal, dann `PYTHONPATH=. .venv/bin/python scripts/testlauf.py`.
"""
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from psycopg.rows import dict_row  # noqa: E402

from app.core.channel import derive_channel  # noqa: E402
from app.core.edit_token import generate_edit_token  # noqa: E402
from app.core.normalize import normalize_name, normalize_phone  # noqa: E402
from app.db import get_connection  # noqa: E402

BASE_URL = "http://127.0.0.1:8731"

created_ids: set[str] = set()
results: list["TestResult"] = []


@dataclass
class TestResult:
    category: str
    name: str
    expected: str
    actual: str
    match: bool
    note: str = ""


# --- Hilfsfunktionen -------------------------------------------------------


def default_form(**overrides) -> dict:
    base = {
        "street": "Teststraße 1",
        "city": "Teststadt",
        "email": f"testlauf-{uuid.uuid4().hex[:10]}@example.com",
        "privacy_accepted": "on",
        "submission_token": str(uuid.uuid4()),
        # 30s in der Vergangenheit: sicher über der 3s-Spam-Zeitschwelle,
        # außer ein Test will genau die auslösen.
        "form_rendered_at": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def submit(data: dict) -> httpx.Response:
    return httpx.post(f"{BASE_URL}/submit", data=data, follow_redirects=False)


def db_fetch_by_token(token: str) -> dict | None:
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM leads WHERE submission_token = %(t)s", {"t": token})
        return cur.fetchone()


def db_fetch(lead_id) -> dict | None:
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM leads WHERE id = %(id)s", {"id": str(lead_id)})
        return cur.fetchone()


def db_events(lead_id) -> list[dict]:
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM lead_events WHERE lead_id = %(id)s ORDER BY created_at ASC", {"id": str(lead_id)}
        )
        return cur.fetchall()


def db_count_by_token(token: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT count(*) FROM leads WHERE submission_token = %(t)s", {"t": token}
        ).fetchone()
        return row[0]


def track(lead_id) -> None:
    if lead_id:
        created_ids.add(str(lead_id))


def record(category: str, name: str, expected: str, actual: str, match: bool, note: str = "") -> None:
    results.append(TestResult(category, name, expected, actual, match, note))
    status = "OK " if match else "!! "
    print(f"[{status}] {category} / {name}")
    if not match:
        print(f"      erwartet:    {expected}")
        print(f"      tatsächlich: {actual}")


def submit_and_get(data: dict) -> tuple[httpx.Response, dict | None]:
    resp = submit(data)
    lead = db_fetch_by_token(data["submission_token"])
    track(lead["id"] if lead else None)
    return resp, lead


# --- 1. Dedup-Fälle (F1-F4 + Mehrfachkette mit Feld-Merge) ----------------


def test_f1_technische_dopplung():
    token = str(uuid.uuid4())
    data = default_form(submission_token=token, email=f"testlauf-f1-{uuid.uuid4().hex[:6]}@example.com")
    resp1, lead1 = submit_and_get(data)
    events_after_1 = db_events(lead1["id"]) if lead1 else []

    resp2 = submit(data)  # exakt derselbe Token, exakt dieselben Daten
    lead_after_2 = db_fetch_by_token(token)
    events_after_2 = db_events(lead_after_2["id"]) if lead_after_2 else []

    expected = (
        "Beide Requests 303; genau 1 Lead-Zeile für den Token; Event- und "
        "email_attempts-Zahl nach dem zweiten Request unverändert (kein "
        "zweiter Insert, kein zweiter Mailversuch)."
    )
    count = db_count_by_token(token)
    actual = (
        f"Request 1: {resp1.status_code}, Request 2: {resp2.status_code}; "
        f"Zeilen für Token: {count}; Events nach 1.: {len(events_after_1)}, "
        f"nach 2.: {len(events_after_2)}; email_attempts nach 2.: "
        f"{lead_after_2['email_attempts'] if lead_after_2 else 'n/a'}"
    )
    match = (
        resp1.status_code == 303
        and resp2.status_code == 303
        and count == 1
        and len(events_after_1) == len(events_after_2)
    )
    record("Dedup", "F1 technische Dopplung (Token-Replay)", expected, actual, match)


def test_f2_duplikat():
    shared = dict(
        street="Duplikatweg 9",
        city="Duplikatstadt",
        email=f"testlauf-f2-{uuid.uuid4().hex[:6]}@example.com",
        phone="0170 3000001",
        message="Identische Anfrage",
    )
    data1 = default_form(submission_token=str(uuid.uuid4()), **shared)
    _, lead1 = submit_and_get(data1)

    data2 = default_form(submission_token=str(uuid.uuid4()), **shared)  # identischer Inhalt, neuer Token
    resp2, lead2 = submit_and_get(data2)

    lead1_after = db_fetch(lead1["id"])
    events1 = db_events(lead1["id"])
    events2 = db_events(lead2["id"]) if lead2 else []

    expected = (
        "2 eigenständige Zeilen; Original bleibt status='neu'; Duplikat hat "
        "status='duplikat' und duplicate_of=Original-ID; Original bekommt "
        "Event 'erneut_angefragt'; beide durchlaufen den Mail-Versuch, anders "
        "als F1 (Konzept §4: F2 -> Mail ja) - geprüft über 'mail_gesendet' ODER "
        "'mail_fehlgeschlagen', da ein gemeinsames Tageslimit (usage_counters) "
        "bei intensivem Testen am selben Tag einen erfolgreichen Versand in "
        "einen regulären Fehlschlag verwandeln kann, ohne dass das ein Bug ist."
    )
    original_erneut_angefragt = any(e["event_type"] == "erneut_angefragt" for e in events1)
    mail_versucht_types = {"mail_gesendet", "mail_fehlgeschlagen"}
    beide_mail = any(e["event_type"] in mail_versucht_types for e in events1) and any(
        e["event_type"] in mail_versucht_types for e in events2
    )
    actual = (
        f"lead1.status={lead1_after['status']!r}, lead2.status={lead2['status'] if lead2 else None!r}, "
        f"lead2.duplicate_of=={lead2['duplicate_of'] if lead2 else None} "
        f"(erwartet {lead1['id']}); erneut_angefragt auf Original: {original_erneut_angefragt}; "
        f"beide mit Mail-Versuch-Event: {beide_mail} "
        f"(lead1: {[e['event_type'] for e in events1]}, lead2: {[e['event_type'] for e in events2]})"
    )
    match = (
        resp2.status_code == 303
        and lead1_after["status"] == "neu"
        and lead2 is not None
        and lead2["status"] == "duplikat"
        and str(lead2["duplicate_of"]) == str(lead1["id"])
        and original_erneut_angefragt
        and beide_mail
    )
    record("Dedup", "F2 Duplikat (identischer Inhalt, neuer Token)", expected, actual, match)


def test_f4_kontakt_bekannt():
    email = f"testlauf-f4-{uuid.uuid4().hex[:6]}@example.com"
    data1 = default_form(
        submission_token=str(uuid.uuid4()), email=email, street="Altbau 1", city="Bremen"
    )
    _, lead1 = submit_and_get(data1)

    data2 = default_form(
        submission_token=str(uuid.uuid4()), email=email, street="Neubau 2", city="Hamburg"
    )
    resp2, lead2 = submit_and_get(data2)

    lead1_after = db_fetch(lead1["id"])
    events2 = db_events(lead2["id"]) if lead2 else []
    kontakt_bekannt_events = [e for e in events2 if e["event_type"] == "kontakt_bekannt"]

    expected = (
        "2 unabhängige aktive Leads (kein duplicate_of/superseded_by auf "
        "beiden Seiten); neuer Lead bekommt Event 'kontakt_bekannt' mit "
        "bekannter_lead_id == Original-ID; Original bleibt unangetastet."
    )
    actual = (
        f"lead1.status={lead1_after['status']!r} superseded_by={lead1_after['superseded_by']}; "
        f"lead2.status={lead2['status'] if lead2 else None!r} duplicate_of={lead2['duplicate_of'] if lead2 else None}; "
        f"kontakt_bekannt-Events auf lead2: {len(kontakt_bekannt_events)}, "
        f"payload={kontakt_bekannt_events[0]['payload'] if kontakt_bekannt_events else None}"
    )
    match = (
        resp2.status_code == 303
        and lead1_after["status"] == "neu"
        and lead1_after["superseded_by"] is None
        and lead2 is not None
        and lead2["duplicate_of"] is None
        and len(kontakt_bekannt_events) == 1
        and str(kontakt_bekannt_events[0]["payload"].get("bekannter_lead_id")) == str(lead1["id"])
    )
    record("Dedup", "F4 Kontakt bekannt (Person matcht, Adresse nicht)", expected, actual, match)


def test_f3_kette_mit_feldmerge():
    """3-stufige Korrekturkette: prüft F3-Klassifikation, dass die
    Kandidatensuche bei jedem Schritt den aktuell aktiven (nicht den
    ursprünglichen) Vorgänger findet, Feld-Merge in beide Richtungen über
    mehrere Sprünge hinweg, und R17 (Status/Zuweisung werden vererbt, nicht
    überschrieben)."""
    street, city = "Kettenweg 5", "Kettenstadt"

    # T1: Basis-Anfrage.
    t1_data = default_form(
        submission_token=str(uuid.uuid4()),
        email=f"testlauf-f3a-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city,
        phone="0170 1111111",
        message="Erste Nachricht",
    )
    _, t1 = submit_and_get(t1_data)

    # R17-Vorbereitung: T1 wird "bearbeitet" (Aktionen-Endpunkt, echte Session).
    import os as _os
    from app.core.admin_auth import generate_session_token
    session_token = generate_session_token("testlauf", _os.environ["SESSION_SECRET"])
    cookies = {"standort_check_admin_session": session_token}
    httpx.post(
        f"{BASE_URL}/admin/leads/{t1['id']}/bearbeitung",
        data={"status": "kontaktiert", "assigned_to": "testlauf-anna", "disqualify_reason": ""},
        cookies=cookies,
    )
    t1_bearbeitet = db_fetch(t1["id"])

    # T2 korrigiert T1: Telefon-Konflikt (neu gewinnt), Anmerkung weggelassen
    # (Lücke, alt füllt), PLZ neu hinzugefügt.
    t2_data = default_form(
        submission_token=str(uuid.uuid4()),
        email=f"testlauf-f3b-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city,
        phone="0170 2222222",
        postal_code="20095",
    )
    _, t2 = submit_and_get(t2_data)
    t1_nach_t2 = db_fetch(t1["id"])

    # T3 korrigiert T2: Telefon UND PLZ weggelassen (sollen von T2 geerbt
    # werden, nicht von T1), Anmerkung neu gesetzt (Konflikt gegen die von
    # T2 geerbte "Erste Nachricht").
    t3_data = default_form(
        submission_token=str(uuid.uuid4()),
        email=f"testlauf-f3c-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city,
        message="Dritte Nachricht",
    )
    _, t3 = submit_and_get(t3_data)
    t2_nach_t3 = db_fetch(t2["id"])

    expected_t2 = (
        "T2.phone_raw='0170 2222222' (Konflikt, neu gewinnt), T2.message="
        "'Erste Nachricht' (Lücke, von T1 übernommen), T2.postal_code="
        "'20095'; T1.status='ersetzt', T1.superseded_by=T2.id; T2 erbt "
        "status='kontaktiert' und assigned_to='testlauf-anna' von T1 (R17)."
    )
    actual_t2 = (
        f"T2.phone_raw={t2['phone_raw']!r} message={t2['message']!r} "
        f"postal_code={t2['postal_code']!r} status={t2['status']!r} "
        f"assigned_to={t2['assigned_to']!r}; T1.status={t1_nach_t2['status']!r} "
        f"superseded_by={t1_nach_t2['superseded_by']}"
    )
    match_t2 = (
        t2["phone_raw"] == "0170 2222222"
        and t2["message"] == "Erste Nachricht"
        and t2["postal_code"] == "20095"
        and t1_nach_t2["status"] == "ersetzt"
        and str(t1_nach_t2["superseded_by"]) == str(t2["id"])
        and t2["status"] == "kontaktiert"
        and t2["assigned_to"] == "testlauf-anna"
    )
    record(
        "Dedup", "F3 Kette Schritt 1->2 (Feld-Merge + R17-Vererbung)", expected_t2, actual_t2, match_t2,
        note=f"T1 vor Korrektur: status={t1_bearbeitet['status']!r} assigned_to={t1_bearbeitet['assigned_to']!r}",
    )

    expected_t3 = (
        "T3.phone_raw='0170 2222222' (Lücke, von T2 geerbt - nicht von T1), "
        "T3.postal_code='20095' (Lücke, von T2 geerbt), T3.message="
        "'Dritte Nachricht' (Konflikt gegen T2s geerbten Wert, neu "
        "gewinnt); T2.status='ersetzt', T2.superseded_by=T3.id (Kandidaten-"
        "suche findet den AKTUELLEN Vorgänger T2, nicht den ursprünglichen T1)."
    )
    actual_t3 = (
        f"T3.phone_raw={t3['phone_raw']!r} postal_code={t3['postal_code']!r} "
        f"message={t3['message']!r}; T2.status={t2_nach_t3['status']!r} "
        f"superseded_by={t2_nach_t3['superseded_by']}"
    )
    match_t3 = (
        t3["phone_raw"] == "0170 2222222"
        and t3["postal_code"] == "20095"
        and t3["message"] == "Dritte Nachricht"
        and t2_nach_t3["status"] == "ersetzt"
        and str(t2_nach_t3["superseded_by"]) == str(t3["id"])
    )
    record("Dedup", "F3 Kette Schritt 2->3 (Merge-Kette über 2 Sprünge)", expected_t3, actual_t3, match_t3)


# --- 2. Spam-Muster (Konzept §J, alle vier) --------------------------------


def _spam_case(name: str, expected_reason: str, **overrides):
    data = default_form(
        submission_token=str(uuid.uuid4()),
        email=f"testlauf-spam-{uuid.uuid4().hex[:6]}@example.com",
        **overrides,
    )
    resp, lead = submit_and_get(data)
    expected = (
        f"is_spam=true, spam_reason='{expected_reason}', status='spam' "
        f"(Konzept §J + Fix aus der letzten Session), keine Mail "
        f"(email_status='uebersprungen')."
    )
    actual = (
        f"HTTP {resp.status_code}; is_spam={lead['is_spam'] if lead else 'n/a'}, "
        f"spam_reason={lead['spam_reason'] if lead else 'n/a'!r}, "
        f"status={lead['status'] if lead else 'n/a'!r}, "
        f"email_status={lead['email_status'] if lead else 'n/a'!r}"
    )
    match = (
        lead is not None
        and lead["is_spam"] is True
        and lead["spam_reason"] == expected_reason
        and lead["status"] == "spam"
        and lead["email_status"] == "uebersprungen"
    )
    record("Spam", name, expected, actual, match)


def test_spam_honeypot():
    _spam_case("Honeypot gefüllt", "honeypot_gefuellt", website="http://bot.example")


def test_spam_zeitschwelle():
    # form_rendered_at auf "jetzt" -> elapsed_seconds < 3s (MIN_SECONDS_BEFORE_SUBMIT).
    _spam_case(
        "Zu schnell abgesendet",
        "zu_schnell_abgesendet",
        form_rendered_at=datetime.now(timezone.utc).isoformat(),
    )


def test_spam_linkzaehler():
    _spam_case(
        "Zwei oder mehr Links in der Anmerkung",
        "zu_viele_links_in_anmerkung",
        message="Schaut mal hier http://a.example und auch hier http://b.example vorbei!",
    )


def test_spam_zeichensatz():
    _spam_case(
        "Fremdes Schriftsystem in der Anmerkung",
        "fremdes_schriftsystem_in_anmerkung",
        message="Привет, это тестовое сообщение на кириллице для den Spam-Filter.",
    )


# --- 3. Pflichtfeld-Verletzungen (einzeln + kombiniert) --------------------


def _pflichtfeld_case(name: str, expected_keys: set[str], **overrides):
    token = str(uuid.uuid4())
    data = default_form(submission_token=token, **overrides)
    resp = submit(data)
    lead_created = db_count_by_token(token) > 0
    body = resp.text
    found_keys = {k for k in expected_keys if _ERROR_TEXT[k] in body}

    expected = (
        f"HTTP 422, Formular re-rendert MIT Fehlermeldungen für {sorted(expected_keys)}, "
        f"kein Lead in der DB gespeichert (Konzept K2: nicht speichern-und-verwerfen, "
        f"sondern ablehnen)."
    )
    actual = (
        f"HTTP {resp.status_code}; gefundene Fehlermeldungen: {sorted(found_keys)}; "
        f"Lead in DB angelegt: {lead_created}"
    )
    match = resp.status_code == 422 and found_keys == expected_keys and not lead_created
    record("Pflichtfelder", name, expected, actual, match)


_ERROR_TEXT = {
    "street": "Bitte Straße und Hausnummer angeben.",
    "city": "Bitte Ort angeben.",
    "email": "Bitte E-Mail-Adresse angeben.",
    "email_invalid": "Bitte eine gültige E-Mail-Adresse angeben.",
    "privacy_accepted": "Bitte Datenschutzerklärung akzeptieren.",
}


def test_pflichtfeld_strasse_fehlt():
    _pflichtfeld_case("Straße fehlt (einzeln)", {"street"}, street=None)


def test_pflichtfeld_ort_fehlt():
    _pflichtfeld_case("Ort fehlt (einzeln)", {"city"}, city=None)


def test_pflichtfeld_email_fehlt():
    _pflichtfeld_case("E-Mail fehlt (einzeln)", {"email"}, email=None)


def test_pflichtfeld_datenschutz_fehlt():
    _pflichtfeld_case("Datenschutz nicht akzeptiert (einzeln)", {"privacy_accepted"}, privacy_accepted=None)


def test_pflichtfeld_email_ungueltig():
    _pflichtfeld_case("E-Mail syntaktisch ungültig", {"email_invalid"}, email="keine-email-adresse")


def test_pflichtfeld_alle_fehlen_kombiniert():
    _pflichtfeld_case(
        "Straße + Ort + E-Mail + Datenschutz fehlen (kombiniert)",
        {"street", "city", "email", "privacy_accepted"},
        street=None, city=None, email=None, privacy_accepted=None,
    )


# --- 4. Ungültige Werte in Auswahlfeldern ----------------------------------


def test_ungueltiger_contact_time_preference():
    token = str(uuid.uuid4())
    data = default_form(submission_token=token, contact_time_preference="nachts")
    resp = submit(data)
    lead_created = db_count_by_token(token) > 0
    has_error = "Ungültige Auswahl." in resp.text

    expected = (
        "contact_time_preference wird gegen die feste Werteliste geprüft "
        "(app/core/validation.py) -> HTTP 422, Fehlermeldung 'Ungültige "
        "Auswahl.', kein Lead gespeichert."
    )
    actual = f"HTTP {resp.status_code}; Fehlermeldung vorhanden: {has_error}; Lead angelegt: {lead_created}"
    match = resp.status_code == 422 and has_error and not lead_created
    record("Auswahlfelder", "contact_time_preference='nachts' (nicht in Werteliste)", expected, actual, match)


def test_ungueltiger_heard_about():
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-heard-{uuid.uuid4().hex[:6]}@example.com",
        heard_about="TikTok-Anzeige",
    )
    resp = submit(data)
    lead = db_fetch_by_token(token)
    track(lead["id"] if lead else None)
    events = db_events(lead["id"]) if lead else []
    hat_unerwarteter_feldwert_event = any(
        e["event_type"] == "unerwarteter_feldwert"
        and e["payload"].get("feld") == "heard_about"
        and e["payload"].get("wert") == "TikTok-Anzeige"
        for e in events
    )

    expected = (
        "normalize_heard_about() erkennt 'TikTok-Anzeige' nicht in HEARD_ABOUT_OPTIONS "
        "-> HTTP 303, heard_about wird als None gespeichert (keine Angabe statt Ablehnung "
        "oder stillem Rohwert), Rohwert bleibt im Event 'unerwarteter_feldwert' erhalten, "
        "derive_channel() bekommt heard_about=None und fällt mangels utm/gclid/fbclid/referrer "
        "auf channel='direkt' zurück."
    )
    actual = (
        f"HTTP {resp.status_code}; heard_about={lead['heard_about'] if lead else 'n/a'!r}, "
        f"channel={lead['channel'] if lead else 'n/a'!r}, channel_source={lead['channel_source'] if lead else 'n/a'!r}, "
        f"unerwarteter_feldwert-Event vorhanden: {hat_unerwarteter_feldwert_event}"
    )
    match = (
        resp.status_code == 303
        and lead is not None
        and lead["heard_about"] is None
        and lead["channel"] == "direkt"
        and hat_unerwarteter_feldwert_event
    )
    record(
        "Auswahlfelder", "heard_about='TikTok-Anzeige' (nicht in Optionsliste)", expected, actual, match,
    )


def test_ungueltiger_is_owner():
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-owner-{uuid.uuid4().hex[:6]}@example.com",
        is_owner="vielleicht",
    )
    resp = submit(data)
    lead = db_fetch_by_token(token)
    track(lead["id"] if lead else None)

    expected = (
        "_parse_is_owner() kennt nur 'ja'/'nein', alles andere wird zu None "
        "(keine Validierung, kein Fehler) -> HTTP 303, is_owner wird NULL "
        "gespeichert statt eines Fehlers."
    )
    actual = f"HTTP {resp.status_code}; is_owner={lead['is_owner'] if lead else 'n/a'!r}"
    match = resp.status_code == 303 and lead is not None and lead["is_owner"] is None
    record("Auswahlfelder", "is_owner='vielleicht' (weder ja noch nein)", expected, actual, match)


# --- 5. Telefonnummern in allen fünf Formaten aus der Aufgabe --------------
# normalize_phone() dient als Orakel (schon per pytest abgedeckt) - hier
# wird nur geprüft, ob der komplette Weg Formular -> DB dasselbe liefert
# wie die reine Funktion direkt, nicht die Normalisierungslogik selbst.


def _telefon_case(raw: str):
    expected_e164, expected_valid = normalize_phone(raw)
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-tel-{uuid.uuid4().hex[:6]}@example.com",
        phone=raw,
    )
    resp = submit(data)
    lead = db_fetch_by_token(token)
    track(lead["id"] if lead else None)

    expected = f"normalize_phone({raw!r}) == ({expected_e164!r}, {expected_valid}) - Formular soll dasselbe in der DB speichern."
    actual = (
        f"HTTP {resp.status_code}; phone_e164={lead['phone_e164'] if lead else 'n/a'!r}, "
        f"phone_valid={lead['phone_valid'] if lead else 'n/a'}"
    )
    match = (
        resp.status_code == 303
        and lead is not None
        and lead["phone_e164"] == expected_e164
        and lead["phone_valid"] == expected_valid
    )
    record("Telefonformate", raw, expected, actual, match)


def test_telefonformate():
    for raw in ["+49 40 / 123 456", "0170 5551234", "040 55512345", "004940123456", "0451 9988776"]:
        _telefon_case(raw)


# --- 6. Namen mit Partikeln und gemischter Schreibweise --------------------
# normalize_name() als Orakel, gleiche Begründung wie bei den Telefonformaten.


def _name_case(raw: str):
    expected_name, expected_normalized = normalize_name(raw)
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-name-{uuid.uuid4().hex[:6]}@example.com",
        name=raw,
    )
    resp = submit(data)
    lead = db_fetch_by_token(token)
    track(lead["id"] if lead else None)

    expected = f"normalize_name({raw!r}) == ({expected_name!r}, {expected_normalized}) - Formular soll dasselbe in der DB speichern, name_raw bleibt roh erhalten."
    actual = (
        f"HTTP {resp.status_code}; name={lead['name'] if lead else 'n/a'!r}, "
        f"name_normalized={lead['name_normalized'] if lead else 'n/a'}, "
        f"name_raw={lead['name_raw'] if lead else 'n/a'!r}"
    )
    match = (
        resp.status_code == 303
        and lead is not None
        and lead["name"] == expected_name
        and lead["name_normalized"] == expected_normalized
        and lead["name_raw"] == raw
    )
    record("Namen", raw, expected, actual, match)


def test_namen():
    for raw in ["TOM AHRENS", "müller-lüdenscheidt", "van der berg", "McDonald", "O'Brien", "di Marco"]:
        _name_case(raw)


# --- 7. Sehr lange Eingaben in allen Textfeldern ---------------------------


def test_lange_eingaben():
    long_street = "Sehr lange Straße " + "A" * 2000
    long_city = "B" * 2000
    long_name = "C" * 5000
    long_message = "D" * 10000 + " Ende der Nachricht"
    long_phone_garbage = "0" + "1" * 500  # zu lang für normalize_phone -> soll ungültig, nicht abstürzen
    long_email = f"testlauf-{'x' * 50}-{uuid.uuid4().hex[:6]}@example.com"

    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        street=long_street, city=long_city, name=long_name, message=long_message,
        phone=long_phone_garbage, email=long_email,
    )
    resp = submit(data)
    lead = db_fetch_by_token(token)
    track(lead["id"] if lead else None)

    expected = (
        "Postgres text-Spalten sind längenunbegrenzt -> ich erwarte HTTP 303, "
        "alle langen Werte werden VOLLSTÄNDIG und unverändert gespeichert "
        "(kein Truncate, kein Absturz); die Telefon-Ziffernfolge ist zu lang "
        "für normalize_phone() -> phone_valid=false statt Fehler."
    )
    lengths_ok = (
        lead is not None
        and lead["street"] == long_street
        and lead["city"] == long_city
        and lead["name_raw"] == long_name
        and lead["message"] == long_message
    )
    actual = (
        f"HTTP {resp.status_code}; "
        f"street-Länge gespeichert={len(lead['street']) if lead else 'n/a'} (erwartet {len(long_street)}); "
        f"city-Länge={len(lead['city']) if lead else 'n/a'} (erwartet {len(long_city)}); "
        f"name_raw-Länge={len(lead['name_raw']) if lead else 'n/a'} (erwartet {len(long_name)}); "
        f"message-Länge={len(lead['message']) if lead else 'n/a'} (erwartet {len(long_message)}); "
        f"phone_valid={lead['phone_valid'] if lead else 'n/a'}; "
        f"exakte Übereinstimmung aller Felder: {lengths_ok}"
    )
    match = resp.status_code == 303 and lengths_ok and lead["phone_valid"] is False
    record("Lange Eingaben", "alle Textfelder gleichzeitig sehr lang (2000-10000 Zeichen)", expected, actual, match)


# --- 8. Sonderzeichen und Emoji im Anmerkungsfeld --------------------------


def test_sonderzeichen_emoji():
    message = (
        'Grüße 🎉🏠 aus München! Fragen: 100% sicher? <script>alert(1)</script> '
        '& "Anführung" \'Apostroph\' — Gedankenstrich, Tabulator:\tEnde.'
    )
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-emoji-{uuid.uuid4().hex[:6]}@example.com",
        message=message,
    )
    resp = submit(data)
    lead = db_fetch_by_token(token)
    track(lead["id"] if lead else None)

    expected = (
        "UTF-8 (inkl. 4-Byte-Emoji) und HTML-Sonderzeichen werden byteidentisch "
        "gespeichert und zurückgelesen; kein Absturz; NICHT als Spam erkannt "
        "(kyrillisch/CJK-Regex greift hier nicht, <2 Links)."
    )
    actual = (
        f"HTTP {resp.status_code}; message identisch zurückgelesen: "
        f"{lead['message'] == message if lead else 'n/a'}; is_spam={lead['is_spam'] if lead else 'n/a'}"
    )
    match = resp.status_code == 303 and lead is not None and lead["message"] == message and lead["is_spam"] is False
    record("Sonderzeichen", "Emoji + Umlaute + HTML-Sonderzeichen + Tab in Anmerkung", expected, actual, match)


# --- 9. Kanal-Ableitung für jede Stufe der Prioritätsliste (Konzept §H) ----


def _kanal_case(name: str, *, utm_source=None, gclid=None, fbclid=None, referrer=None, heard_about=None):
    expected_channel, expected_source = derive_channel(
        utm_source=utm_source, gclid=gclid, fbclid=fbclid, referrer=referrer, heard_about=heard_about
    )
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-kanal-{uuid.uuid4().hex[:6]}@example.com",
        utm_source=utm_source, gclid=gclid, fbclid=fbclid, referrer=referrer, heard_about=heard_about,
    )
    resp = submit(data)
    lead = db_fetch_by_token(token)
    track(lead["id"] if lead else None)

    expected = f"derive_channel(...) == ({expected_channel!r}, {expected_source!r})"
    actual = (
        f"HTTP {resp.status_code}; channel={lead['channel'] if lead else 'n/a'!r}, "
        f"channel_source={lead['channel_source'] if lead else 'n/a'!r}"
    )
    match = (
        resp.status_code == 303
        and lead is not None
        and lead["channel"] == expected_channel
        and lead["channel_source"] == expected_source
    )
    record("Kanal-Ableitung", name, expected, actual, match)


def test_kanal_ableitung():
    _kanal_case("Stufe 1a: utm_source exakt ('google')", utm_source="google")
    _kanal_case("Stufe 1b: utm_source Substring-Fallback ('google-partner-blog')", utm_source="google-partner-blog")
    _kanal_case("Stufe 1c: utm_source unbekannt ('newsletter-mai')", utm_source="newsletter-mai")
    _kanal_case("Stufe 2: gclid vorhanden, kein utm_source", gclid="abc123")
    _kanal_case("Stufe 3: fbclid vorhanden, kein utm_source/gclid", fbclid="xyz789")
    _kanal_case(
        "Stufe 4a: referrer Google, nichts davor",
        referrer="https://www.google.com/search?q=standort-check",
    )
    _kanal_case(
        "Stufe 4b: referrer Bing, nichts davor",
        referrer="https://www.bing.com/search?q=standort-check",
    )
    _kanal_case("Stufe 5: heard_about, nichts davor", heard_about="Empfehlung")
    _kanal_case("Stufe 6: nichts von alledem -> direkt")


# --- 10. Geocoding, Retry, Korrekturfenster, Korrektur-Link (Phase 5) -----
# Anders als die Fälle oben: diese brauchen einen echten Retry-Lauf (echte
# Nominatim-/Brevo-Aufrufe unter DRY_RUN_EMAIL) - process_after wird direkt
# in der DB vorgezogen statt eine Stunde zu warten (Konzept §G, dieselbe
# Wirkung wie PROCESS_DELAY_MINUTES=0).


def _verify_address_free(street: str, city: str) -> None:
    """Sicherheitsnetz nach dem Vorfall vom 17.08.: ein Testlauf, der eine
    Straße+Ort-Kombination verwendet, die bereits ein ECHTER (nicht per
    'testlauf-%' erkennbarer) Lead trägt, wird von persist_submission()
    als F3-Korrektur behandelt - der echte Lead wird stillschweigend mit
    Fake-Testdaten überschrieben, exakt dieselbe Prüfung wie
    app/submission.py::_find_dedup_candidate(). Genau das geschah mit dem
    echten "Am Mühlenteich 7, Groß Grönau"-Beispiellead (eine der fünf
    Aufgaben-Beispieladressen) - wieder hergestellt, aber nicht nochmal
    riskieren. Bricht hart ab statt eine Kollision einzugehen."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, email FROM leads
            WHERE status NOT IN ('duplikat', 'ersetzt', 'spam')
              AND email NOT ILIKE 'testlauf-%%'
              AND lower(trim(street)) = %(street_norm)s AND lower(trim(city)) = %(city_norm)s
            LIMIT 1
            """,
            {"street_norm": street.strip().lower(), "city_norm": city.strip().lower()},
        ).fetchone()
    if row is not None:
        raise RuntimeError(
            f"SICHERHEITSABBRUCH: Adresse {street!r}/{city!r} matcht einen bereits "
            f"vorhandenen, echten Lead ({row[1]}, id={row[0]}) - ein Testlauf würde "
            f"das als F3-Korrektur fehlinterpretieren und den echten Lead überschreiben "
            f"(genau der Vorfall vom 17.08. mit Groß Grönau). Testadresse in diesem "
            f"Skript ändern, nicht diese Prüfung entfernen."
        )


def _force_process_after_now(lead_id) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE leads SET process_after = now() WHERE id = %(id)s", {"id": str(lead_id)})


def _trigger_retry() -> dict:
    resp = httpx.post(
        f"{BASE_URL}/admin/retry", headers={"X-Retry-Secret": os.environ["RETRY_SECRET"]}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def test_geocode_nur_ort_gross_groenau():
    # Gleicher Ort wie der echte Beispiellead (lead_nummer 15), aber eine
    # eindeutig erfundene Straße statt "Am Mühlenteich 7" - sonst matcht
    # _find_dedup_candidate() über Straße+Ort und behandelt diesen Testlauf
    # als F3-Korrektur des echten Leads (Vorfall 17.08., s. docs/FUNDE.md).
    street, city = "Phantomweg 123", "Groß Grönau"
    _verify_address_free(street, city)
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-nurort-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city,
    )
    _, lead = submit_and_get(data)
    _force_process_after_now(lead["id"])
    _trigger_retry()
    lead_final = db_fetch(lead["id"])

    expected = (
        "Erfundene Straße in einem real auflösbaren Ort -> Ortsebene-"
        "Rückfall greift -> geocode_status='nur_ort', geo_state="
        "'Schleswig-Holstein', traffic_light='gelb'."
    )
    actual = (
        f"geocode_status={lead_final['geocode_status']!r}, geo_state={lead_final['geo_state']!r}, "
        f"traffic_light={lead_final['traffic_light']!r}, traffic_light_reason={lead_final['traffic_light_reason']!r}"
    )
    match = (
        lead_final["geocode_status"] == "nur_ort"
        and lead_final["geo_state"] == "Schleswig-Holstein"
        and lead_final["traffic_light"] == "gelb"
    )
    record("Geocoding", "nur_ort-Rückfall: erfundene Straße in Groß Grönau", expected, actual, match)


def test_geocode_ausland_wien():
    # Bewusst OHNE postal_code: "1010" (vierstellig, österreichisch) würde
    # an validate_submission()s 5-stelligem PLZ-Format scheitern (422) -
    # ein eigener Fund (s. docs/TESTLAUF.md): eine reale ausländische PLZ
    # kann im aktuellen Formular gar nicht eingegeben werden, nur weggelassen.
    street, city = "Stephansplatz 1", "Wien"
    _verify_address_free(street, city)
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-ausland-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city,
    )
    _, lead = submit_and_get(data)
    _force_process_after_now(lead["id"])
    _trigger_retry()
    lead_nach_geocoding = db_fetch(lead["id"])
    # Zweiter Lauf: die Auslandsmail wurde beim ersten Retry erst auf
    # 'offen' gesetzt (Konzept §A), braucht denselben process_after-Trick
    # nochmal, um sie im selben Testlauf ohne Wartezeit zu erreichen.
    _force_process_after_now(lead["id"])
    _trigger_retry()
    lead_final = db_fetch(lead["id"])

    expected = (
        "Wien ohne countrycodes=de auffindbar (docs/FUNDE.md) -> status="
        "'ausland', in_service_area=False, geo_country='AT', traffic_light="
        "'rot'; zweiter Retry-Lauf verarbeitet ausland_hinweis_status "
        "offen -> simuliert (DRY_RUN_EMAIL)."
    )
    actual = (
        f"nach 1. Retry: status={lead_nach_geocoding['status']!r}, in_service_area={lead_nach_geocoding['in_service_area']}, "
        f"geo_country={lead_nach_geocoding['geo_country']!r}, traffic_light={lead_nach_geocoding['traffic_light']!r}; "
        f"nach 2. Retry: ausland_hinweis_status={lead_final['ausland_hinweis_status']!r}"
    )
    match = (
        lead_nach_geocoding["status"] == "ausland"
        and lead_nach_geocoding["in_service_area"] is False
        and lead_nach_geocoding["geo_country"] == "AT"
        and lead_nach_geocoding["traffic_light"] == "rot"
        and lead_final["ausland_hinweis_status"] in ("simuliert", "gesendet")
    )
    record("Geocoding", "Auslandspfad: Stephansplatz 1, Wien (Konzept §A)", expected, actual, match)


def test_geocode_lindenweg_neustadt_aufgabenbeispiel():
    # ACHTUNG: "Lindenweg 3, Neustadt" ist eine der fünf echten Aufgaben-
    # Beispieladressen - _verify_address_free() lässt diesen Test bewusst
    # mit einem klaren Fehler abbrechen, solange ein echter (nicht
    # testlauf-%) Lead mit dieser Adresse aktiv ist, statt ihn zu
    # überschreiben (genau das ist am 18.08. einmal fast passiert, s.
    # docs/FUNDE.md). Erst laufen lassen, wenn kein echter Lead mehr diese
    # Adresse belegt, oder Testadresse in diesem Fall ändern.
    street, city = "Lindenweg 3", "Neustadt"  # keine PLZ, wie im Aufgabenbeispiel
    _verify_address_free(street, city)
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-lindenweg-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city,
    )
    _, lead = submit_and_get(data)
    _force_process_after_now(lead["id"])
    _trigger_retry()
    lead_final = db_fetch(lead["id"])

    expected = (
        "Aufgabenbeispiel ohne PLZ: 'mehrdeutig' (drei Bundesländer -"
        "Baden-Württemberg/Schleswig-Holstein/Sachsen, der eigentliche Sinn "
        "dieses Beispiels). Ein zwischenzeitlich exakter Ortsnamen-Abgleich "
        "(18.08.) hatte das kurz auf 'nicht_gefunden' verschärft, weil "
        "keiner von Nominatims Kandidaten exakt 'Neustadt' heißt (sondern "
        "z.B. 'Neustadt im Schwarzwald') - ein Rückschritt, am 19.08. durch "
        "einen Enthalten-Vergleich (s. docs/FUNDE.md) wieder korrigiert."
    )
    actual = f"geocode_status={lead_final['geocode_status']!r}, traffic_light={lead_final['traffic_light']!r}"
    match = lead_final["geocode_status"] == "mehrdeutig" and lead_final["traffic_light"] == "gelb"
    record("Geocoding", "Aufgabenbeispiel Lindenweg 3, Neustadt", expected, actual, match)


def test_ampel_ohne_telefon():
    # Bewusst NICHT "Osterstraße 88, Hamburg" (das ist lead_nummer 14, eine
    # der fünf echten Aufgaben-Beispieladressen) - andere, unbenutzte
    # Adresse, kein PLZ-Rateversuch (falsch geratene PLZ würde jetzt
    # geocode_status='plz_abweichend' statt 'ok' ergeben und den Testfall
    # verfälschen, s. docs/FUNDE.md).
    street, city = "Grüner Weg 12", "Leipzig"
    _verify_address_free(street, city)
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-ohnetelefon-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city,  # phone bewusst weggelassen
    )
    _, lead = submit_and_get(data)
    _force_process_after_now(lead["id"])
    _trigger_retry()
    lead_final = db_fetch(lead["id"])

    expected = (
        "Vollständig geokodete Adresse, aber kein Telefon angegeben -> "
        "Ampel gelb 'Nur per E-Mail erreichbar' (Konzept §B)."
    )
    actual = (
        f"geocode_status={lead_final['geocode_status']!r}, traffic_light={lead_final['traffic_light']!r}, "
        f"traffic_light_reason={lead_final['traffic_light_reason']!r}"
    )
    match = (
        lead_final["geocode_status"] == "ok"
        and lead_final["traffic_light"] == "gelb"
        and lead_final["traffic_light_reason"] == "Nur per E-Mail erreichbar"
    )
    record("Ampel", "Ohne Telefon -> gelb 'Nur per E-Mail erreichbar'", expected, actual, match)


def test_korrekturfenster_entfaellt():
    street, city = "Korrekturfensterweg 1", "Hamburg"
    _verify_address_free(street, city)
    token1 = str(uuid.uuid4())
    data1 = default_form(
        submission_token=token1,
        email=f"testlauf-fenster-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city, phone="0170 4000001",
    )
    _, lead1 = submit_and_get(data1)
    # Bewusst KEIN _force_process_after_now: der Vorgänger soll bei der
    # Korrektur noch geocode_status='offen' sein, wie im echten 1h-Fenster
    # (Konzept §G) - genau der Fall, den die Korrektur abfangen soll.

    token2 = str(uuid.uuid4())
    data2 = default_form(
        submission_token=token2,
        email=f"testlauf-fenster-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city, phone="0170 4000001",  # gleiches Telefon -> F3-Match über die Person
        message="Korrektur innerhalb des Fensters",
    )
    _, lead2 = submit_and_get(data2)
    lead1_nach_korrektur = db_fetch(lead1["id"])

    expected = (
        "F3-Korrektur innerhalb des 1h-Fensters: Vorgänger (noch "
        "geocode_status='offen') wird auf 'entfaellt' gesetzt, seine "
        "Verarbeitung entfällt (Konzept §G)."
    )
    actual = f"lead1.geocode_status nach Korrektur={lead1_nach_korrektur['geocode_status']!r} (vorher 'offen')"
    match = lead1_nach_korrektur["geocode_status"] == "entfaellt"
    record("Korrekturfenster", "F3 innerhalb 1h-Fenster setzt Vorgänger auf entfaellt", expected, actual, match)


def test_korrektur_link_vorbefuellung():
    street, city = "Editlinkweg 3", "Editlinkstadt"
    _verify_address_free(street, city)
    token = str(uuid.uuid4())
    email = f"testlauf-editlink-{uuid.uuid4().hex[:6]}@example.com"
    data = default_form(
        submission_token=token, email=email,
        street=street, city=city, name="Editlink Test",
    )
    _, lead = submit_and_get(data)

    edit_token = generate_edit_token(str(lead["id"]), os.environ["EDIT_TOKEN_SECRET"])
    resp = httpx.get(f"{BASE_URL}/?k={edit_token}")

    expected = "GET /?k=<Token> rendert das Formular mit vorbefüllten Werten (Straße, Ort, Name, E-Mail)."
    vorbefuellt = (
        "Editlinkweg 3" in resp.text
        and "Editlinkstadt" in resp.text
        and "Editlink Test" in resp.text
        and email in resp.text
    )
    actual = f"HTTP {resp.status_code}; alle vier Werte im HTML gefunden: {vorbefuellt}"
    match = resp.status_code == 200 and vorbefuellt
    record("Korrektur-Link", "GET /?k=Token befüllt das Formular vor", expected, actual, match)


def test_retry_heilung_fehlgeschlagene_mail():
    street, city = "Heilungsweg 1", "Heilungsstadt"
    _verify_address_free(street, city)
    token = str(uuid.uuid4())
    data = default_form(
        submission_token=token,
        email=f"testlauf-heilung-{uuid.uuid4().hex[:6]}@example.com",
        street=street, city=city,
    )
    _, lead = submit_and_get(data)

    with get_connection() as conn:
        conn.execute(
            "UPDATE leads SET email_status='fehlgeschlagen', email_last_error='künstlicher Testfehler', "
            "process_after=now() WHERE id=%(id)s",
            {"id": str(lead["id"])},
        )
    _trigger_retry()
    lead_geheilt = db_fetch(lead["id"])

    expected = (
        "Künstlich auf 'fehlgeschlagen' gesetzte Mail wird vom Retry erneut "
        "versucht. Unter DRY_RUN_EMAIL wird sie 'simuliert' statt 'gesendet' "
        "- ein echter Fehlschlag-und-Erholung-Test mit absichtlich falschen "
        "Brevo-Zugangsdaten bleibt Marcos manueller Test (nicht mit "
        "Produktions-Zugangsdaten automatisierbar)."
    )
    actual = f"email_status nach Retry={lead_geheilt['email_status']!r} (vorher künstlich 'fehlgeschlagen' gesetzt)"
    match = lead_geheilt["email_status"] in ("simuliert", "gesendet")
    record("Retry", "Künstlich fehlgeschlagene Mail wird vom Retry erneut versucht", expected, actual, match)


# --- Aufräumen + Report -----------------------------------------------------


def cleanup() -> int:
    if not created_ids:
        return 0
    ids = list(created_ids)
    with get_connection() as conn:
        conn.execute("DELETE FROM lead_events WHERE lead_id = ANY(%(ids)s)", {"ids": ids})
        result = conn.execute("DELETE FROM leads WHERE id = ANY(%(ids)s)", {"ids": ids})
        deleted = result.rowcount
    return deleted


def write_report(path: Path) -> None:
    total = len(results)
    ok = sum(1 for r in results if r.match)
    mismatches = [r for r in results if not r.match]
    findings = [r for r in results if r.note]

    lines = [
        "# Testlauf: Randfälle",
        "",
        f"Programmatischer Testlauf gegen die echte Datenbank über "
        f"`scripts/testlauf.py` (POST /submit + direkte DB-Prüfung, kein Mock, "
        f"kein pytest-Ersatz - die reinen Funktionen bleiben in `tests/core/`). "
        f"Erstellt am {datetime.now(timezone.utc).astimezone().strftime('%d.%m.%Y')}. "
        f"Testdaten wurden nach dem Lauf gelöscht (exakt getrackte IDs, kein "
        f"Muster-Löschen).",
        "",
        f"**Ergebnis: {ok}/{total} Fälle wie erwartet.**"
        + (f" {len(mismatches)} Abweichung(en), s. unten." if mismatches else " Keine Abweichungen."),
        "",
        "Wo Erwartung und tatsächliches Verhalten auseinanderfallen, wurde NICHTS "
        "repariert - das ist zur Entscheidung vorgelegt, s. \"Abweichungen\" am Ende.",
        "",
    ]

    by_category: dict[str, list[TestResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    for category, items in by_category.items():
        lines.append(f"## {category}")
        lines.append("")
        for r in items:
            status = "✅" if r.match else "⚠️"
            lines.append(f"### {status} {r.name}")
            lines.append("")
            lines.append(f"**Erwartet:** {r.expected}")
            lines.append("")
            lines.append(f"**Tatsächlich:** {r.actual}")
            if r.note:
                lines.append("")
                lines.append(f"**Hinweis:** {r.note}")
            lines.append("")

    if mismatches:
        lines.append("## Abweichungen (zur Entscheidung, nicht selbst repariert)")
        lines.append("")
        for r in mismatches:
            lines.append(f"- **{r.category} / {r.name}** — erwartet: {r.expected} — tatsächlich: {r.actual}")
        lines.append("")

    # Nur Notes, die als echter Fund markiert sind (Präfix "FUND:") landen in
    # der Zusammenfassung - reine Kontext-Notizen (z.B. R17-Ausgangszustand)
    # stehen nur beim jeweiligen Fall selbst, nicht nochmal hier oben.
    other_findings = [r for r in findings if r.match and r.note.startswith("FUND:")]
    if other_findings:
        lines.append("## Sonstige Funde (Verhalten wie erwartet, aber bemerkenswert)")
        lines.append("")
        for r in other_findings:
            lines.append(f"- **{r.category} / {r.name}** — {r.note}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    try:
        httpx.get(f"{BASE_URL}/health", timeout=5)
    except httpx.ConnectError:
        print(f"FEHLER: Server unter {BASE_URL} nicht erreichbar. Erst starten:")
        print("  .venv/bin/uvicorn app.main:app --port 8731")
        sys.exit(1)

    # Sicherheitsnetz (Fund 17.08., s. docs/FUNDE.md): die meisten Fälle
    # oben verwenden den gemeinsamen Default "Teststraße 1"/"Teststadt"
    # (default_form()) ohne eigene Straße/Ort - matcht das bereits ein
    # echter, nicht-testlauf Lead, würde jeder nachfolgende Testfall als
    # F3-Korrektur dieser Kette missverstanden. Einmal zentral geprüft statt
    # in jeder einzelnen der ~15 Funktionen, die den Default nutzen.
    _verify_address_free("Teststraße 1", "Teststadt")

    try:
        test_f1_technische_dopplung()
        test_f2_duplikat()
        test_f4_kontakt_bekannt()
        test_f3_kette_mit_feldmerge()

        test_spam_honeypot()
        test_spam_zeitschwelle()
        test_spam_linkzaehler()
        test_spam_zeichensatz()

        test_pflichtfeld_strasse_fehlt()
        test_pflichtfeld_ort_fehlt()
        test_pflichtfeld_email_fehlt()
        test_pflichtfeld_datenschutz_fehlt()
        test_pflichtfeld_email_ungueltig()
        test_pflichtfeld_alle_fehlen_kombiniert()

        test_ungueltiger_contact_time_preference()
        test_ungueltiger_heard_about()
        test_ungueltiger_is_owner()

        test_telefonformate()
        test_namen()
        test_lange_eingaben()
        test_sonderzeichen_emoji()
        test_kanal_ableitung()

        # Geocoding/Retry/Korrekturfenster/Korrektur-Link (Phase 5) - echte
        # Nominatim-/Retry-Aufrufe, deshalb eigene Pausen zusätzlich zur
        # eingebauten Ratenbegrenzung in app/geocoding.py.
        test_geocode_nur_ort_gross_groenau()
        time.sleep(2)
        test_geocode_ausland_wien()
        time.sleep(2)
        test_geocode_lindenweg_neustadt_aufgabenbeispiel()
        time.sleep(2)
        test_ampel_ohne_telefon()
        time.sleep(1)
        test_korrekturfenster_entfaellt()
        test_korrektur_link_vorbefuellung()
        test_retry_heilung_fehlgeschlagene_mail()
    finally:
        report_path = Path(__file__).resolve().parent.parent / "docs" / "TESTLAUF.md"
        write_report(report_path)
        deleted = cleanup()
        print(f"\n{'=' * 70}")
        print(f"Ergebnis: {sum(1 for r in results if r.match)}/{len(results)} Fälle wie erwartet.")
        print(f"Report geschrieben: {report_path}")
        print(f"Aufgeräumt: {deleted} Lead-Zeilen (von {len(created_ids)} getrackten IDs) gelöscht.")


if __name__ == "__main__":
    main()
