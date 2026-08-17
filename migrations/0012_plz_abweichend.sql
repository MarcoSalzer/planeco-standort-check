-- Marco, 2026-08-18 (s. docs/FUNDE.md): countrycodes=de wurde aus der
-- Nominatim-Abfrage entfernt (Auslandsadressen waren sonst strukturell nie
-- auffindbar). Ohne Ländereinschränkung braucht es einen Abgleich Eingabe
-- vs. Ergebnis - dabei zeigte sich, dass eine fehlende und eine tatsächlich
-- abweichende PLZ zwei verschiedene Dinge sind: fehlt sie in der Antwort
-- (z.B. bei Verwaltungsgrenzen-Objekten wie Dörfern), ist das kein
-- Widerspruch; weicht sie tatsächlich ab, soll der Treffer nicht verworfen
-- werden, sondern sichtbar als 'plz_abweichend' markiert sein.

alter table leads drop constraint leads_geocode_status_check;
alter table leads add constraint leads_geocode_status_check
  check (geocode_status in ('offen', 'ok', 'mehrdeutig', 'nicht_gefunden',
                             'fehlgeschlagen', 'entfaellt', 'simuliert',
                             'nur_ort', 'plz_abweichend'));

-- Die von Nominatim tatsächlich GEFUNDENE PLZ (nicht die Eingabe, die
-- bereits in postal_code steht) - nur bei geocode_status='plz_abweichend'
-- inhaltlich von postal_code verschieden, sonst meist gleich oder leer.
alter table leads add column geo_postal_code text;
