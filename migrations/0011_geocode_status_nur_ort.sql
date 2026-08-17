-- Erweitert geocode_status um 'nur_ort' (Marco, 2026-08-18, nach dem
-- OSM-Fund in docs/FUNDE.md: die Straße "Am Mühlenteich" in Groß Grönau
-- ist in OpenStreetMap nicht erfasst, PLZ+Ort allein aber sauber
-- auflösbar). app/geocoding.py::geocode() versucht bei 'nicht_gefunden'
-- automatisch einen zweiten, strukturierten Versuch nur mit PLZ+Ort; gelingt
-- der, wird 'nur_ort' gesetzt statt 'nicht_gefunden' - Bundesland/Gemeinde/
-- Koordinaten stehen dann auf Ortsebene, die Ampel zeigt gelb statt rot mit
-- einem Text, der die Ursache benennt (Kartendatenlücke, keine
-- Falscheingabe) statt einen Tippfehler zu unterstellen.

alter table leads drop constraint leads_geocode_status_check;
alter table leads add constraint leads_geocode_status_check
  check (geocode_status in ('offen', 'ok', 'mehrdeutig', 'nicht_gefunden',
                             'fehlgeschlagen', 'entfaellt', 'simuliert',
                             'nur_ort'));
