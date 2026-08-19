"""Anzeige-Formatierung fürs Dashboard (CLAUDE.md Regel 7).

Datenbank speichert timestamptz in UTC; Anzeige ist immer Europe/Berlin,
nie naive datetimes. zoneinfo statt fixem Offset, damit die Sommerzeit-
Umstellung automatisch stimmt.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo("Europe/Berlin")


def format_berlin_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("format_berlin_datetime: naive datetime ohne tzinfo übergeben")
    return value.astimezone(_BERLIN).strftime("%d.%m.%Y %H:%M")


def format_address(street: str, postal_code: str | None, city: str) -> str:
    """Straße + PLZ + Ort als eine Zeile - geteilt zwischen der
    Bestätigungsmail (app/mail.py) und der Adress-Spalte im Dashboard
    (app/admin.py), damit beide Stellen nicht unabhängig voneinander
    formatieren und dabei auseinanderlaufen können."""
    if postal_code:
        return f"{street}, {postal_code} {city}"
    return f"{street}, {city}"


def berlin_today_iso() -> str:
    """Für Dateinamen (CSV-Export): sortierbares YYYY-MM-DD in Europe/Berlin,
    bewusst nicht datetime.now().date() (das wäre UTC-Datum, kann nahe
    Mitternacht vom Berliner Kalendertag abweichen)."""
    return datetime.now(_BERLIN).strftime("%Y-%m-%d")


# Anzeigetexte für contact_time_preference (Werte s. app/core/validation.py).
# Aus app/mail.py hierher verschoben, damit Dashboard und Bestätigungsmail
# dieselbe Quelle verwenden statt zweier unabhängiger Kopien.
CONTACT_TIME_LABELS: dict[str, str] = {
    "vormittags": "Vormittags",
    "nachmittags": "Nachmittags",
    "abends": "Abends",
    "flexibel": "Flexibel",
}

# Vereinigung aller status-artigen Spaltenwerte (status, email_status,
# geocode_status, ausland_hinweis_status - Migrationen 0001-0004). Werte wie
# 'offen'/'gesendet'/'fehlgeschlagen' bedeuten in jeder dieser Spalten
# dasselbe, ein gemeinsames Dictionary ist deshalb unproblematisch. Deckt
# zugleich die ASCII-Ersatzschreibweisen ab (uebersprungen, entfaellt -
# CHECK-Constraints vermeiden Umlaute), die ein reines .capitalize() nicht
# richtig anzeigen würde.
STATUS_VALUE_LABELS: dict[str, str] = {
    "neu": "Neu",
    "kontaktiert": "Kontaktiert",
    "qualifiziert": "Qualifiziert",
    "disqualifiziert": "Disqualifiziert",
    "duplikat": "Duplikat",
    "ersetzt": "Ersetzt",
    "spam": "Spam",
    "ausland": "Ausland",
    "offen": "Offen",
    "gesendet": "Gesendet",
    "fehlgeschlagen": "Fehlgeschlagen",
    "simuliert": "Simuliert (Dry-Run)",
    "uebersprungen": "Übersprungen",
    "ok": "OK",
    "mehrdeutig": "Mehrdeutig",
    "nicht_gefunden": "Nicht gefunden",
    "nur_ort": "Nur Ort bestätigt",
    "plz_abweichend": "PLZ weicht ab",
    "entfaellt": "Entfällt",
    "nicht_noetig": "Nicht nötig",
}


def status_label(value: str | None) -> str:
    if not value:
        return "–"
    return STATUS_VALUE_LABELS.get(value, value)


# Anzeigetexte für lead_events.event_type (Konzept §2/§K8). status_geaendert/
# zugewiesen/geocodiert werden von keinem Code-Pfad vor Aktionen/Phase 4
# geschrieben, hier trotzdem schon vollständig, damit die Event-Historie
# nicht nachgezogen werden muss, sobald sie es tun.
EVENT_TYPE_LABELS: dict[str, str] = {
    "erstellt": "Erstellt",
    "status_geaendert": "Status geändert",
    "zugewiesen": "Zugewiesen",
    "mail_gesendet": "Bestätigungsmail gesendet",
    "mail_fehlgeschlagen": "Bestätigungsmail fehlgeschlagen",
    "geocodiert": "Geocoding abgeschlossen",
    "erneut_angefragt": "Erneut angefragt",
    "ersetzt": "Durch Korrektur ersetzt",
    "kontakt_bekannt": "Kontakt bereits bekannt",
    "unerwarteter_feldwert": "Unerwarteter Feldwert (als „keine Angabe“ gespeichert)",
    "notiz_hinzugefuegt": "Notiz hinzugefügt",
}


def format_duration_de(value: timedelta | None) -> str:
    """Für "Ø Zeit bis Erstkontakt" (Konzept §7) - Postgres liefert
    avg(contacted_at - created_at) als Interval, psycopg als timedelta."""
    if value is None:
        return "–"
    total_minutes = round(value.total_seconds() / 60)
    if total_minutes < 60:
        return f"{total_minutes} Min."
    total_hours, minutes = divmod(total_minutes, 60)
    if total_hours < 24:
        return f"{total_hours} Std. {minutes} Min."
    days, hours = divmod(total_hours, 24)
    return f"{days} Tag(e) {hours} Std."
