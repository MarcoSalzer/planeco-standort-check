"""Kontingent-Schutz für Free-Tier-Dienste (Brevo, Nominatim).

Enthält nur die Konfigurationswerte. Die eigentliche Durchsetzung
(Dry-Run-Zweig, Zähler in usage_counters, serielle Nominatim-Anfragen)
folgt in Phase 2 — dieses Modul wird aktuell von nichts importiert.
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
