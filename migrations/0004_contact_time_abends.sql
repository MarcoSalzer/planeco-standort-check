-- contact_time_preference um 'abends' erweitert (Konzept-Chat, 2026-08-16).
-- Werte danach: vormittags, nachmittags, abends, flexibel.

alter table leads drop constraint leads_contact_time_preference_check;
alter table leads add constraint leads_contact_time_preference_check
  check (contact_time_preference in ('vormittags', 'nachmittags', 'abends', 'flexibel')
         or contact_time_preference is null);
