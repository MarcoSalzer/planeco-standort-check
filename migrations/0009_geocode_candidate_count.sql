-- Phase 4 Block c/d: geocode_candidate_count als eigene Spalte statt nur im
-- lead_events-Payload. Für 'mehrdeutig' die Anzahl WIRKLICH verschiedener
-- Orte (app/core/geocoding.py: candidate_count), nicht die rohe
-- Nominatim-Trefferzahl (die steht getrennt davon in
-- geocode_raw.auswahl.kandidaten_gesamt). Wird für den Ampel-Grundtext
-- ("Adresse mehrdeutig: N mögliche Orte") gebraucht, den Block c jetzt
-- beim Schreiben statt bei jedem Lesen berechnet - dafür muss der Wert
-- als Spalte abrufbar sein, nicht nur transient beim Geocoding-Aufruf.

alter table leads add column geocode_candidate_count integer;
