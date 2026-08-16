-- Lead-Nummer: fortlaufende, menschenlesbare Nummer pro echtem Vorgang
-- (Marco, 2026-08-16). Eine Postgres-Sequenz statt max(lead_nummer)+1,
-- damit die Vergabe bei gleichzeitigen Submits eindeutig bleibt (kein
-- Lost-Update zwischen zwei parallelen Requests). Lücken (z.B. durch eine
-- zurückgerollte Transaktion nach nextval()) sind laut Marco in Ordnung -
-- Sequenzen sind in Postgres bewusst nicht transaktional.
--
-- lead_nummer ist NICHT unique: F2/F3 erben die Nummer des Originals, ein
-- Vorgang kann also mehrere Zeilen mit derselben Nummer haben (die Zeile
-- mit dem jeweils aktuellen Stand ist über status/superseded_by weiterhin
-- eindeutig bestimmbar). Keine NOT-NULL-Constraint, weil bestehende
-- Zeilen bis zum Backfill (scripts/backfill_lead_nummer.py) NULL sind.

create sequence lead_nummer_seq;
alter table leads add column lead_nummer integer;
create index leads_lead_nummer_idx on leads (lead_nummer);
