-- Erweitert email_status um 'simuliert' für DRY_RUN_EMAIL (Konzept-Chat, 2026-08-15).
-- 0001_init.sql ist bereits gegen die produktive Supabase-Instanz gelaufen
-- (Tabellen existieren) - deshalb hier ein ALTER statt die Datei rückwirkend
-- zu ändern.
--
-- 'simuliert': DRY_RUN_EMAIL=true lässt die komplette Mail-Logik (Statusfelder,
-- Events) laufen, nur der echte Brevo-Aufruf unterbleibt. Ohne einen eigenen
-- Wert wäre ein Dry-Run von einem echten Versand ('gesendet') nicht zu
-- unterscheiden.

alter table leads drop constraint leads_email_status_check;
alter table leads add constraint leads_email_status_check
  check (email_status in ('offen', 'gesendet', 'fehlgeschlagen', 'skipped', 'simuliert'));
