-- Erweitert ausland_hinweis_status um 'simuliert' für DRY_RUN_EMAIL
-- (Konzept §A, Auslandspfad), analog 0002_email_status_simuliert.sql und
-- 0007_geocode_status_simuliert.sql. Ohne einen eigenen Wert wäre ein
-- Dry-Run-Versand der Auslandshinweis-Mail von einem echten, erfolgreichen
-- Versand ('gesendet') nicht zu unterscheiden.

alter table leads drop constraint leads_ausland_hinweis_status_check;
alter table leads add constraint leads_ausland_hinweis_status_check
  check (ausland_hinweis_status in ('nicht_noetig', 'offen', 'gesendet',
                                     'fehlgeschlagen', 'simuliert'));
