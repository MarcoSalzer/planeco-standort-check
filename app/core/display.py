"""Anzeige-Formatierung fürs Dashboard (CLAUDE.md Regel 7).

Datenbank speichert timestamptz in UTC; Anzeige ist immer Europe/Berlin,
nie naive datetimes. zoneinfo statt fixem Offset, damit die Sommerzeit-
Umstellung automatisch stimmt.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

_BERLIN = ZoneInfo("Europe/Berlin")


def format_berlin_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("format_berlin_datetime: naive datetime ohne tzinfo übergeben")
    return value.astimezone(_BERLIN).strftime("%d.%m.%Y %H:%M")
