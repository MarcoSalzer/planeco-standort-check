"""Kontingent-/Timing-Konfiguration für Free-Tier-Dienste (Brevo, Nominatim)
und die verzögerte Verarbeitung (Konzept §G).

Enthält nur die Konfigurationswerte, gelesen beim Modul-Import (fail fast
mit klarer Meldung statt eines später unbemerkt falschen Verhaltens - s.
docs/FUNDE.md zu SERVICE_AREA_STATES/PROCESS_DELAY_MINUTES). Die eigentliche
Durchsetzung (Dry-Run-Zweige, Zähler in usage_counters, serielle
Nominatim-Anfragen) liegt in app/mail.py und app/retry.py.
"""
import os


def _bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _required_int_env(name: str) -> int:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} ist nicht gesetzt.")
    return int(value)


DRY_RUN_EMAIL = _bool_env("DRY_RUN_EMAIL")
DRY_RUN_GEOCODE = _bool_env("DRY_RUN_GEOCODE")
MAX_EMAILS_PER_DAY = _required_int_env("MAX_EMAILS_PER_DAY")
MAX_GEOCODE_PER_MINUTE = _required_int_env("MAX_GEOCODE_PER_MINUTE")

# Verzögerte Verarbeitung, Konzept §G: Geocoding (und alle weiteren
# Nebenwirkungen außer der sofortigen Bestätigungsmail) warten bis
# process_after. War bislang nur als Env in .env.example dokumentiert, ohne
# dass ein Code-Pfad sie gelesen hätte - process_after bekam ausschließlich
# den SQL-Spaltendefault (fest 1h). Praktisch relevant, weil sich die
# Verzögerung für eine Demo kurzzeitig herabsetzen lassen soll, s.
# docs/FUNDE.md.
PROCESS_DELAY_MINUTES = _required_int_env("PROCESS_DELAY_MINUTES")

# Kurze, wiederholbare Portionsgröße pro Retry-Aufruf (Marco, 2026-08-17),
# getrennt von MAX_GEOCODE_PER_MINUTE: MAX_GEOCODE_PER_MINUTE ist eine
# Ratenbremse gegenüber Nominatim, GEOCODE_BATCH_SIZE bestimmt unabhängig
# davon, wie viele Leads EIN Aufruf von POST /admin/retry überhaupt versucht
# - bei 1s Abstand zwischen Anfragen (Nominatim-Nutzungsbedingungen) dauert
# eine Portion von 5 rund 5s, das passt in jedes Serverless-Zeitlimit. Ein
# nicht verarbeiteter Rest wartet auf den nächsten Cron-Lauf (alle 15 min).
GEOCODE_BATCH_SIZE = _required_int_env("GEOCODE_BATCH_SIZE")
