-- geo_state_unresolved: sichtbar machen, wenn ein eindeutiger/über-
-- einstimmender Geocoding-Treffer trotzdem kein Bundesland liefert (auch
-- nach ISO-3166-2-Fallback für die Stadtstaaten, s. app/core/geocoding.py)
-- - sonst nicht von "noch nicht geprüft" zu unterscheiden (Fund 2026-08-17,
-- docs/FUNDE.md). Gleiches Muster wie name_normalized: ein eigenes Bool
-- neben dem Wert selbst, statt die Unsicherheit im Wert (geo_state=NULL)
-- zu verstecken.

alter table leads add column geo_state_unresolved boolean not null default false;
