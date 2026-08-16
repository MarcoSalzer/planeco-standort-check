-- Bestandsbereinigung: leere Strings in den neun Attributionsfeldern zu
-- NULL. app/main.py normalisierte bislang nur heard_about/phone/name so
-- (`or None`), nicht die Attributionsfelder - das Hidden-Formularfeld
-- sendet bei fehlendem UTM-Parameter value="" statt gar keinen Wert.
-- Fund beim Bauen des Auswertungs-Tabs (docs/FUNDE.md): '' und NULL
-- landeten als zwei verschiedene GROUP-BY-Gruppen in jeder Auswertung
-- nach diesen Spalten. Code-Fix in app/main.py (2026-08-16); hier nur die
-- Bestandsdaten nachgezogen, keine schema-Änderung nötig.

update leads set
  utm_source   = nullif(utm_source, ''),
  utm_medium   = nullif(utm_medium, ''),
  utm_campaign = nullif(utm_campaign, ''),
  utm_term     = nullif(utm_term, ''),
  utm_content  = nullif(utm_content, ''),
  gclid        = nullif(gclid, ''),
  fbclid       = nullif(fbclid, ''),
  referrer     = nullif(referrer, ''),
  landing_page = nullif(landing_page, '')
where utm_source = '' or utm_medium = '' or utm_campaign = '' or utm_term = ''
   or utm_content = '' or gclid = '' or fbclid = '' or referrer = '' or landing_page = '';
