-- Erweitert geocode_status um 'simuliert' für DRY_RUN_GEOCODE (Phase 4
-- Block b), analog 0002_email_status_simuliert.sql. Ohne einen eigenen Wert
-- wäre ein Dry-Run-Geocoding (voller Ablauf: Kontingent-Zähler, Versuche,
-- Event, nur der echte Nominatim-Aufruf unterbleibt) von einem echten,
-- erfolgreichen Versuch nicht zu unterscheiden.

alter table leads drop constraint leads_geocode_status_check;
alter table leads add constraint leads_geocode_status_check
  check (geocode_status in ('offen', 'ok', 'mehrdeutig', 'nicht_gefunden',
                             'fehlgeschlagen', 'entfaellt', 'simuliert'));
