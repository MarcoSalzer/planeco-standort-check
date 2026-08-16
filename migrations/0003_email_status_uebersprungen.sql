-- email_status='skipped' -> 'uebersprungen' (Konzept-Chat, 2026-08-16).
-- Grund: K8 verlangt deutsche Statuswerte, 'skipped' war ein Übernahme-Fehler
-- aus dem englischen Wortlaut im ursprünglichen Konzept-Fließtext (§2).
-- 'simuliert' war schon deutsch und bleibt unverändert.
--
-- UPDATE vor dem Constraint-Wechsel, falls zwischenzeitlich Zeilen mit
-- 'skipped' entstanden sind (zum Zeitpunkt dieser Migration: keine).

update leads set email_status = 'uebersprungen' where email_status = 'skipped';

alter table leads drop constraint leads_email_status_check;
alter table leads add constraint leads_email_status_check
  check (email_status in ('offen', 'gesendet', 'fehlgeschlagen', 'uebersprungen', 'simuliert'));
