# Standort-Check: To-do (v2)

## Aktueller Stand

Dieser Abschnitt fasst den Stand zusammen. Die Phasen-Checklisten weiter
unten (ab "## Phase 0") bleiben als detailliertes Verlaufsmaterial stehen,
auch was hier oben schon knapper zusammengefasst ist - für NOTES.md
(Phase 6) nützlich, für den Überblick nicht nötig.

**Nichts unfertig/uncommittet:** `git status` zeigt "nothing to commit,
working tree clean", `origin/main` ist auf dem aktuellen Stand. Kein
Punkt aus diesem Stand hängt in einem halbfertigen Zustand.

### ⚠️ Zwischenfall: ein echter Beispiel-Lead wurde kurz überschrieben, ist aber vollständig wiederhergestellt

Beim automatisierten Testlauf (s. "Nächste Schritte" unten) verwendete ein
neuer Testfall versehentlich exakt dieselbe Adresse ("Am Mühlenteich 7,
Groß Grönau") wie der echte Beispiel-Lead `lead_nummer 15` - eine der
fünf Aufgaben-Beispieladressen. `persist_submission()` behandelte die
Testabgabe deshalb als F3-Korrektur: der echte Lead wurde auf
`status='ersetzt'` gesetzt, ein Fake-Testdatensatz wurde die neue
führende Version. Aufgefallen, weil das anschließende Aufräumen an einer
Fremdschlüssel-Verkettung scheiterte. **Vollständig von Hand
wiederhergestellt** (status/superseded_by aus der Event-Historie
rekonstruiert - keine `status_geaendert`-Events vorhanden, also zweifelsfrei
`status='neu'`/`superseded_by=NULL` vor dem Vorfall; fälschliches
`ersetzt`-Event entfernt; Fake-Lead gelöscht) und verifiziert: die Kette
steht exakt wie vor dem Testlauf, inklusive des vorherigen legitimen
`nur_ort`-Fixes. **Kein Datenverlust, aber knapp.**

Direkt behoben: `scripts/testlauf.py` hat jetzt `_verify_address_free()` -
bricht vor jedem risikobehafteten Testfall (und einmal zentral für den von
~15 Fällen gemeinsam genutzten Default "Teststraße 1"/"Teststadt") hart ab,
wenn die Adresse bereits einem echten (nicht `testlauf-%`) Lead gehört,
statt eine Kollision einzugehen. Betroffene Testadressen auf eindeutig
erfundene Straßen in denselben Orten umgestellt. Voller Bericht inkl.
Beweisführung in docs/FUNDE.md unter „Ein Testfall überschrieb kurzzeitig
einen echten Beispiel-Lead".

**Nebenfund dabei, unabhängig vom obigen Zwischenfall:** 23 Zeilen in der
Datenbank sehen wie nie aufgeräumter Entwickler-Testmüll aus früheren
Testläufen aus (`block3-test-playwright`, `aktionen-test-`, `retry-test-`,
`quota-test`, `batch-test-0` bis `batch-test-7`, Orte `Teststadt`/
`Testort`). Umgang damit noch nicht entschieden - relevant für "Nächste
Schritte" Punkt 2 unten (vollständiges Löschen vor Abgabe).

### Geocoding: aktueller technischer Stand nach der Untersuchung

Ausgangspunkt war ein konkreter Fund: "Am Mühlenteich 7, Groß Grönau"
(eine der fünf Aufgaben-Beispieladressen) wurde als `nicht_gefunden`
gemeldet, bei Hamburger Adressen fehlte gelegentlich das Bundesland.
Untersuchung und Fixe liefen in mehreren Runden, Endstand:

1. **Ortsebene-Rückfall** (`app/geocoding.py::geocode()`): liefert die
   strukturierte Abfrage MIT Straße null Treffer, folgt automatisch ein
   zweiter Versuch NUR mit PLZ+Ort (1,1s Pause, Ratenbegrenzung gilt pro
   Nominatim-Anfrage, nicht nur pro Lead). Erfolg → `geocode_status=
   'nur_ort'` (Migration 0011), Bundesland/Gemeinde/Koordinaten auf
   Ortsebene, Ampel gelb "Ort bestätigt, Straße nicht in der Karte
   gefunden" statt Rot ohne Information.
2. **`countrycodes=de` entfernt.** War seit Phase 4 Block a in jeder
   Nominatim-Abfrage gesetzt - der komplette Auslandspfad (Konzept §A)
   konnte dadurch NIE über eine echte Anfrage auslösen, nur mit von Hand
   konstruierten Testdaten geprüft worden. Die Ländereinschränkung gehört
   in `SERVICE_AREA_STATES`/`in_service_area` (Geschäftslogik), nicht in
   die Suchanfrage.
3. **Ohne Ländereinschränkung: Abgleich Eingabe vs. Ergebnis nötig**
   (`app/core/geocoding.py::parse_nominatim_results()`), sonst reproduziert
   sich derselbe Fehlertyp nur schlimmer (Nominatim fand für "Wien"
   unscharf einen gleichnamigen Weiler in Bayern). Ortsname ist ein hartes
   Kriterium (muss mit mindestens einem Nominatim-Ortsfeld übereinstimmen,
   Normalisierung wie beim Duplikat-Vergleich). PLZ ist weich, **mit einer
   wichtigen Unterscheidung**: fehlt sie in der Antwort (Verwaltungsgrenzen-
   Objekte wie Dörfer liefern grundsätzlich keine), ist das KEIN
   Widerspruch; weicht sie TATSÄCHLICH ab, wird der Treffer nicht
   verworfen, sondern `geocode_status='plz_abweichend'` (Migration 0012,
   neue Spalte `geo_postal_code` für die gefundene PLZ), Ampel gelb "PLZ
   weicht ab: eingegeben X, gefunden Y". **Diese Unterscheidung (fehlender
   Wert ≠ falscher Wert) trat bei der Untersuchung dreimal auf** (Telefon
   in `ampel()`, dann PLZ und Bundesland/Land) - beim nächsten Anfassen
   einer Prüfung dieser Art immer zuerst fragen, ob "kein Wert" und
   "falscher Wert" richtig getrennt sind.
4. **`in_service_area` primär über `country_code`.** Nominatim liefert das
   immer, unabhängig davon, ob ein `state`-Feld existiert. Ist das Land
   nicht `DE`, ist die Adresse außerhalb - unabhängig vom Bundesland. Erst
   wenn das Land `DE` ist (oder unbekannt), entscheidet weiterhin
   `SERVICE_AREA_STATES`. Behebt nebenbei, dass Länder ohne eigenes
   `state`-Feld (Wien liefert wie deutsche Stadtstaaten keins, nur
   `ISO3166-2-lvl4`) sonst nie als außerhalb erkannt worden wären.

Konzept §B (Ampel-Tabelle) und `app/core/ampel.py` sind aktuell (Zeilen 9
`nur_ort`/10 `plz_abweichend`, `nicht_gefunden`-Text präzisiert: "Adresse
im Kartendienst nicht gefunden" statt der Tippfehler-Unterstellung). Live
gegen die echte API UND end-to-end mit zurückgerollten Transaktionen
verifiziert (Groß Grönau → `nur_ort`; Wien → `ausland` + simulierte
zweite Mail, zum ersten Mal über einen echten Nominatim-Aufruf).

**Abgestimmt, keine Abweichung:** "Lindenweg 3, Neustadt" (Aufgabenbeispiel,
ohne PLZ) ergibt mit dem strengen Ortsnamen-Abgleich jetzt `nicht_gefunden`
statt `mehrdeutig`, weil keiner von Nominatims Kandidaten exakt "Neustadt"
heißt (sondern z.B. "Neustadt im Schwarzwald"). Bewusst nicht auf
Teilstring-Toleranz aufgeweicht. (Diese Einschätzung wurde später selbst
korrigiert, s. "Rückschritt behoben" weiter unten.)

### ✅ Erledigt: PLZ-Validierung blockierte echte ausländische Postleitzahlen

`validate_submission()` verlangte bei angegebener PLZ 5 Stellen (deutsches
Format) - eine Wien-Testabgabe mit PLZ "1010" (vierstellig, österreichisch,
korrekt) scheiterte deshalb mit 422. Entschieden: gelockert auf 4-10
Zeichen, Ziffern und Buchstaben erlaubt (deckt auch alphanumerische Formate
wie NL/GB ab); die inhaltliche Prüfung übernimmt ohnehin das Geocoding
(`plz_abweichend`). `app/core/validation.py`, Konzept §3.1 nachgezogen,
drei neue Tests in `tests/core/test_validation.py`.

### Was sonst noch fertig wurde (nach den "Nächste Schritte" der vorherigen Übergabe)

- **Adress-Spalte in der Liste:** Straße+PLZ+Ort als eine Spalte
  (`app/core/display.py::format_address`, geteilt mit der Bestätigungsmail),
  Maps-Symbol daneben. Bundesland bleibt eigene Spalte (wird gefiltert).
- **Inline-Bearbeitung Status/Zugewiesen in der Liste**
  (`POST /admin/leads/{id}/schnellbearbeitung`, `app/admin.py::
  quick_update_lead`): speichert per `fetch()` im Hintergrund, kein
  Neuladen. Fällt eine Zeile durch die Änderung aus dem aktiven Filter,
  bleibt sie sichtbar mit gelbem Hinweis stehen statt kommentarlos zu
  verschwinden (Prüfung läuft über dieselbe `_fetch_leads()`-WHERE-Logik
  wie die Liste). Nur die fünf manuell setzbaren Status editierbar,
  `duplikat`/`ersetzt`/`ausland` bleiben Detailansicht-only (409
  serverseitig erzwungen).
- **Status `disqualifiziert` verlangt jetzt einen Grund**, serverseitig
  erzwungen in beiden Aktionspfaden (Liste: Prompt beim Auswählen;
  Detailansicht: `required`-Attribut folgt dem Status).
- **Feld-Diff bei F3-Korrekturen** in der Ereignis-Historie der
  Detailansicht lesbar (`changed_fields`/`merged_fields` aus dem
  `ersetzt`-Event auf deutsche Labels gemappt) statt rohem Payload-Dump.
- **Mail-Status deutlich sichtbar** über dem "Erneut senden"-Button
  (farbige Zeile, Zeitpunkt, ggf. Fehlermeldung).
- **Karten-Link in der Detailansicht jetzt klickbar** (war reiner Text
  ohne `<a>`-Tag - Nebenfund, behoben mit `markupsafe.Markup`).
- **Auslandspfad nach Konzept §A vollständig gebaut** (zweite Mail,
  `status='ausland'`, `expansion_opt_in`-Formularfeld) - Details s. Punkt 4
  der vorherigen "Nächste Schritte"-Liste, jetzt Verlaufsmaterial in der
  Phase-4-Checkliste unten.
- **Landesbauordnungs-Zuordnung (Konzept §C) bewusst gestrichen**, kein
  Bauauftrag mehr - Begründung für NOTES.md vorgemerkt (nicht Teil der
  Aufgabenstellung, keine externe Schnittstelle).
- **Deploy + GitHub-Actions-Cron live verifiziert:** Build läuft,
  `/health`/Formular/Dashboard online geprüft, Cron manuell ausgelöst,
  grün.

### Aktueller Modul-Stand (`app/`) — nur Ergänzungen seit der letzten Übergabe

- `geocoding.py` / `core/geocoding.py` — kein `countrycodes=de` mehr,
  Ortsebene-Rückfall, Abgleich Eingabe vs. Ergebnis
  (`parse_nominatim_results()` verlangt jetzt `expected_postal_code`/
  `expected_city`), `in_service_area` primär über `country_code`. Neues
  Feld `GeocodeResult.geo_postal_code`.
- `core/ampel.py` — Regeln `nur_ort` (Zeile 9) und `plz_abweichend`
  (Zeile 10) ergänzt, `nicht_gefunden`-Text präzisiert. Neuer Parameter
  `geo_postal_code`.
- `admin.py` — `quick_update_lead()` (Schnellbearbeitung), Diff-Aufbereitung
  für Ereignis-Historie, Mail-Status-Hinweis, `_resolve_dashboard_params()`
  nimmt jetzt ein `query_params`-Mapping statt eines vollen `Request`
  entgegen (wiederverwendbar für die Schnellbearbeitung).
- `mail.py` — `send_auslandshinweis_email()` (zweite Mail, Konzept §A).
- `retry.py` — `_flag_as_ausland()`, dritter Retry-Zweig
  `_retry_auslandshinweis()`. `NOMINATIM_MIN_INTERVAL_SECONDS` jetzt in
  `app/geocoding.py` definiert (eine Quelle der Wahrheit), hier nur importiert.
- Migrationen bis `migrations/0012_plz_abweichend.sql`, alle bereits gegen
  die produktive Supabase-Instanz gelaufen (0010 `ausland_hinweis_status`
  simuliert, 0011 `nur_ort`, 0012 `plz_abweichend` + `geo_postal_code`-Spalte).
- `scripts/testlauf.py` — sieben neue Fälle für Phase 5 (Geocoding-
  Rückfälle, Auslandspfad, Korrekturfenster, Korrektur-Link, Retry-Heilung),
  `_verify_address_free()`-Sicherheitsnetz (s. Zwischenfall oben).

### Tests

192 Tests, alle grün: `.venv/bin/python -m pytest -q`.

### Nächste Schritte, in dieser Reihenfolge [überholt die Fassung oben]

Überholt durch den tatsächlichen Ablauf: Die Datenbank wurde vollständig
geleert (leads/lead_events/usage_counters, `lead_nummer_seq` auf 1
zurückgesetzt - der alte Testmüll aus Punkt 2 unten ist damit erledigt)
und die fünf Beispielanfragen wurden direkt über das echte Formular live
eingetippt (Vercel), statt vorher nochmal `scripts/testlauf.py` laufen zu
lassen - der automatisierte Testlauf blieb dadurch bewusst aus (hätte
ohnehin mit genau diesen Adressen kollidiert, s. `_verify_address_free()`).
Die PLZ-Validierung wurde repariert (s. "Sonstiges, noch offen" unten), die
fünf Punkte aus der anschließenden Abnahme sind bearbeitet (s.
"Abnahme-Rückmeldung, Runde 1" unten).

**Aktueller Stand:** Bau abgeschlossen (bestätigt nach einer zweiten
Abnahme-Rückmeldungsrunde, s. unten - nicht schon nach der ersten). Übrig:
Phase 5 (verbleibende manuelle Prüfpunkte durchgehen, s. Checkliste unten
- viele Punkte sind mit den fünf Beispielanfragen bereits mitgeprüft) und
Phase 6 (NOTES.md, README, Repo-Hygiene, Abgabe).

### Abnahme-Rückmeldung, Runde 1 (fünf Punkte)

Die fünf Beispielanfragen wurden live eingetippt (Vercel) und fünf Punkte
zurückgemeldet, alle bearbeitet:

1. **Rückschritt behoben:** Der zuvor eingeführte exakte Ortsnamen-Abgleich
   (s. "Geocoding: aktueller technischer Stand" oben) ließ "Neustadt" nicht
   mehr auf "Neustadt im Schwarzwald" passen - "Lindenweg 3, Neustadt"
   (Aufgabenbeispiel) fiel dadurch von `mehrdeutig` (drei Bundesländer, der
   eigentliche Sinn des Beispiels) auf `nicht_gefunden`. Nach demselben
   Prinzip wie andere Funde in diesem Projekt: die vorherige Verschärfung
   war selbst der Fehler, kein Fortschritt. Jetzt Enthalten-Vergleich
   (`app/core/geocoding.py::_ort_stimmt_ueberein`) statt exaktem Vergleich -
   live gegen die echte API erneut geprüft (ohne DB-Schreibzugriff, um die
   gerade eingetippten echten Leads nicht zu gefährden): Lindenweg/Neustadt
   wieder `mehrdeutig` (3 Kandidaten), Groß Grönau weiterhin `nur_ort`,
   Hamburg mit falscher PLZ weiterhin `plz_abweichend`, Wien weiterhin
   `ausland` - PLZ-Abweichungs-Logik unberührt, da sie unabhängig vom
   Ortsnamen-Filter erst am gewählten Kandidaten prüft.
2. **"Nur per E-Mail erreichbar" trotz eingegebener Telefonnummer -
   ungeklärt.** DB read-only geprüft: alle vier realen Beispiel-Leads
   (Ahrens/Beckmann/Ruthenberg/Klöpper) haben `phone_valid=true` und einen
   korrekt normalisierten `phone_e164`. Die einzigen zwei Zeilen mit
   dieser Ampel-Meldung heißen `name='Testlauf'` und haben `phone_raw=NULL`
   (kein Telefon eingegeben, nicht nur ungültig), mit Zeitstempeln vor der
   eigentlichen Beispielanfragen-Serie - vermutlich ein separater,
   bewusster Test des Phase-5-Punkts "Lead ohne Telefon". **Nicht
   reproduzierbar mit den aktuellen Daten** - falls das doch einen der
   fünf Leads betrifft, bitte Lead-Nummer/Namen nennen.
3. **Hinweistext gekürzt** wie vorgegeben ("Verarbeitet liegengebliebene
   Leads außerhalb des Korrekturfensters. Läuft sonst automatisch alle 15
   Minuten."). Die ausführliche Begründung (Ausnahmefall, Bezug zu den
   Zeilen-Buttons) jetzt in `docs/KONZEPT.md` §6 statt in der Oberfläche.
4. **`expansion_opt_in` umbenannt zu `marketing_opt_in`** (Migration
   `0014_marketing_opt_in.sql`) - der Name passte nicht mehr zum
   allgemeinen Formulartext ("neue Angebote und Entwicklungen"). Die
   Auslandsmail selbst reflektiert weiterhin gezielt den Regionsbezug,
   dort ist der Kontext (Ausland erkannt) klar.
5. **Bewusst nicht umgesetzt: Rückschreiben telefonisch bestätigter
   Adressdaten.** Bei drei der fünf Beispieladressen stimmten die
   Angaben nicht (falsche PLZ, eine in OpenStreetMap fehlende Straße, ein
   mehrdeutiger Ortsname) - das System erkennt und markiert das
   zuverlässig (Ampel gelb/rot mit konkretem Grund), bietet aber keinen
   Weg, eine im Telefonat geklärte, bestätigte Adresse zurück in den Lead
   zu schreiben. Eine Prüfliste je Lead ("Adresse mit Kunde bestätigt: ja/
   nein") plus ein eigenes Feld für die bestätigte Adresse wären der
   nächste Schritt - bewusst nicht gebaut (Zeitrahmen des Case), aber ein
   echter, im Live-Betrieb sofort spürbarer nächster Ausbauschritt.

### Abnahme-Rückmeldung, Runde 2 (drei Punkte) — danach Bau abgeschlossen ✅

1. **Interne Entwicklungsstand-Hinweise aus der Oberfläche entfernt.** Die
   Auswertungsseite zeigte mehrere Absätze Erklärung, darunter "Bundesland
   kommt aus dem Geocoding (Phase 4, noch nicht gebaut)" - interne
   Projektplanung im Produkt, die nicht mal mehr stimmte. Honesty-Hint auf
   eine Zeile gekürzt, die restliche Erklärung als Tooltip an den
   betreffenden Spaltenüberschriften. Ganze Anwendung auf weitere Stellen
   geprüft (Templates + Python-Strings, die gerendert werden) - keine
   weiteren gefunden.
2. **Retry-Button-Widerspruch behoben.** "0 wartend" + deaktiviert sah aus
   wie "nichts zu tun", obwohl Leads im Korrekturfenster lagen (live
   bestätigt: 0 wartend, 2 im Korrekturfenster). Hinweistext zeigt jetzt
   immer beide Zahlen, mit Zusatzsatz, wenn ausschließlich Leads im
   Fenster liegen. Button bleibt wie besprochen nur für Leads außerhalb
   des Fensters zuständig.
3. **Bau abgeschlossen.** Nächster Schritt: NOTES.md (Phase 6) - kein
   weiterer Bauauftrag erwartet, nur noch Abnahme-Reste (Checkliste unten)
   und Notizen/Abgabe.

### ✅ Duplikat-Erkennung: F3 verlangte fälschlich nur die Adresse

`app/core/dedup.py::dedup_decision()` prüfte die Adresse vor der Person und
gab bei einem Adresstreffer sofort F3 zurück, ohne die Person überhaupt noch
zu prüfen - Konzept §4 sieht für F3 aber Person UND Grundstück vor. Zwei
verschiedene Personen, die dasselbe Grundstück anfragen, wurden dadurch wie
eine Korrektur desselben Vorgangs behandelt: die zweite Person erbte
automatisch `status`/`assigned_to`/`contacted_at` der ersten, und der
Datensatz der ersten Person wurde `status='ersetzt'`, obwohl er inhaltlich
weiterhin galt.

Behoben durch einen neuen fünften Fall statt einer Sonderbehandlung: **F5,
"Grundstück bekannt"** - Adresse matcht, Person nicht → eigenständiger
neuer Lead mit eigener Lead-Nummer, kein Merge, kein Erben von
Bearbeitungsstand, keine `superseded_by`-Verkettung, nur ein Dashboard-Badge
"Grundstück bereits angefragt" mit Verweis auf die andere Anfrage. F3
verlangt seitdem beides (Person UND Adresse), symmetrisch zu F4 (nur
Person). Konzept §4 nachgezogen (Tabelle, Match-Kriterien, Prüfreihenfolge).

**Demo-Daten geprüft, nichts betroffen:** Beide bestehenden
`superseded_by`-Ketten (Lead-Nummer 4, drei Versionen; Lead-Nummer 8, zwei
Versionen) haben in jedem Schritt sowohl identische Adresse als auch
identische E-Mail - beide bleiben unter der neuen, strengeren Regel
korrekt F3. Kein Fall von zwei verschiedenen Personen an derselben Adresse
existiert aktuell in den Demo-Daten; nichts musste nachträglich korrigiert
werden.

**Bewusste Grenze, nicht geändert:** Es gibt kein Zeitfenster für F3 - eine
Korrektur von vor zehn Minuten und eine erneute Anfrage derselben Person
nach sechs Monaten werden identisch behandelt (Merge + geerbter
Bearbeitungsstand). Das ist fachlich fraglich: nach längerer Zeit ist eine
erneute Anfrage eher eine neue Gelegenheit als eine Korrektur desselben
Vorgangs (ein möglicherweise längst abgeschlossener Sales-Vorgang würde
durch die Korrektur wieder geöffnet, mit veraltetem `assigned_to`). Bewusst
nicht gebaut (würde eine weitere Zeitschwelle plus deren Begründung
verlangen, ohne im Rahmen dieses Case belastbar bestimmbar zu sein) - als
offener Punkt für NOTES.md/Livegang vermerkt.

### Sonstiges, noch offen (kein Bauauftrag, nur Erinnerung)

- **F2-Mailtext gegengelesen:** `app/mail.py`,
  `_INTRO_TEXT_BY_CASE[DedupCase.F2_DUPLIKAT]` - Gedankenstrich korrekt
  gesetzt, Text liest sich sauber. Kein Änderungsbedarf.
- **CSV noch nicht in Excel geöffnet** (steht noch aus).
- **`app/config.py`-Docstring war bereits korrigiert** (geprüft: die
  beanstandete Zeile "wird von nichts importiert" existiert im aktuellen
  Docstring nicht mehr, laut `git log` schon im zweiten Commit des Moduls
  ersetzt - dieser TODO-Punkt war selbst veraltet).
- **✅ MX-Prüfung/Tippfehler-Vorschlag bei E-Mail** (Konzept §D) -
  ursprünglich als Scope-Cut entschieden, dann doch noch gebaut (Zeit
  gewonnen). Serverseitig: `app/email_check.py::check_email_mx()`
  (email-validator, `check_deliverability=True`, Timeout 2s), lehnt bei
  bestätigt nicht zustellbarer Domain (NXDOMAIN, kein MX/A/AAAA) mit 422 ab;
  bei ausgefallenem DNS-Dienst/Timeout wird die Adresse angenommen und
  `email_mx_status='nicht_pruefbar'` gesetzt (Migration 0013) - kostet nie
  einen Lead. Clientseitig: Levenshtein-Vorschlag gegen 20 häufige Domains
  in `form.html` ("Meinten Sie gmail.com?"), kein Blocker. Live gegen echte
  Domains verifiziert, inkl. eines Grenzfalls: `gmial.com` existiert
  tatsächlich mit eigenem Mailserver, die MX-Prüfung lässt sie also
  passieren - genau dafür ergänzt der Tippfehler-Vorschlag die MX-Prüfung,
  statt sie zu duplizieren.

## Phase 0 — Konzept fixieren (Chat) ✅
- [x] Datenmodell + Pipeline + Risiken (KONZEPT v2)
- [x] Review-Runde: Felder, Duplikat-Semantik, Mail-Regel, Konflikte K1-K6
- [x] Review 2: Pflichtfelder, Ampel, Feld-Merge, Auswertungs-Tab, deutsche Statuswerte
- [x] Review 3: Auslandspfad, Ampelregeln, Bundesland-Mapping, E-Mail-Prüfung, Mail-Ausnahmen
- [x] Review 4: Korrekturfenster 1h, Kanal-Ableitung, Namens-Normalisierung, Spam-Muster, Kontakt im Footer
- [x] Nur noch offen: nichts. Konzept ist final.

## Phase 1 — Accounts & Skelett ✅
- [x] Accounts nach SETUP.md Schritt 1: Brevo zuerst (Verifizierung!), dann Supabase, Vercel, GitHub
- [x] Lokaler Ordner + git init + docs/ (SETUP.md Schritt 2), CLAUDE.md ins Wurzelverzeichnis
- [x] Repo `planeco-standort-check` (public), .env.example, attribution-Setting
- [x] FastAPI-Skelett deployed auf Vercel, URL erreichbar
- [x] Schema v2 in Supabase (leads + lead_events), Testzeile schreiben/lesen
- [x] Env-Variablen bei Vercel
- **Abbruchkriterium:** läuft das nicht → Ursache klären, nicht auf wackligem Deploy weiterbauen

## Phase 2 — Kernpfad ✅
- [x] Formular mit Feldliste §3.1 v3 (nur Adresse+E-Mail+Datenschutz Pflicht, Rest optional markiert)
- [x] Hidden Fields: utm_*, gclid, fbclid, referrer, landing_page, token, rendered_at, Honeypot
- [x] POST /submit: Server-Validierung (422 re-rendert MIT Eingaben), Normalisierung, content_hash, Dedup-Entscheidung F1-F4, INSERT, PRG
- [x] F3 Feld-Merge (neu gewinnt bei Konflikt, alt füllt Lücken) + superseded-Kette + Events mit changed_fields/merged_fields
- [x] E-Mail-Validierung: Client type=email + JS-Tippfehlervorschlag; Server Syntax (email-validator) — **MX-Prüfung ergänzt, s. "Sonstiges, noch offen" oben**
- [x] Namens-Normalisierung (nur bei durchgaengig GROSS/klein), name_raw erhalten, Tabellentest inkl. McDonald/van der Berg/Mueller-Luedenscheidt
- [x] Kanal-Ableitung beim INSERT: channel + channel_source nach Prioritaetsliste, Tabellentest
- [x] process_after setzen (Env PROCESS_DELAY_MINUTES) — mit Phase 4 Block (c) verdrahtet, s. docs/FUNDE.md
- [x] Kontakthinweis im Formular-Footer und auf Fehlerseiten (Env-Variablen)
- [x] Bestätigungsmail: HTML-Template (Datenzusammenfassung, Korrektur-Hinweis, Erwartung, Kontaktblock), best effort, Statusfelder
- [x] Mail-Ausnahmen: nur F1 und Spam bekommen keine Mail (Konzept §E)
- [x] Korrektur-Link mit Vorbefuellung: signiertes Token (itsdangerous, 7 Tage), GET /?k=... befuellt Formular, kein Schreibzugriff
- [x] Spam-Erkennung: Honeypot, Zeitschwelle, Link-Zaehler im message-Feld, Zeichensatz-Heuristik
- [x] pytest: normalize_phone (5 Beispielformate), content_hash-Stabilität, dedup_decision F1-F4, merge_fields (neu/leer/beide leer)

## Phase 3 — Dashboard ✅
- [x] Login (Env-Credentials, signierter Cookie, constant-time) — live getestet, funktioniert
- [x] Tabs Neu/In Bearbeitung/Erledigt/Alle; duplicate/superseded/spam/ausland in Neu/Bearbeitung/Erledigt default aus (Toggle "alles anzeigen"), in Alle umgekehrt default AN (Toggle blendet aus)
- [x] Spalten inkl. Bundesland, Ampel (traffic_light, seit Block c bei jedem Schreibvorgang berechnet statt live), Kanal (channel + heard_about getrennt) — Beschriftungen durchgängig deutsch, Volltextsuche über Name/E-Mail/Telefon/Ort, Leerzustand mit Meldung statt leerer Tabelle. Im Browser getestet, funktioniert. Adresse (Straße+PLZ+Ort) eine Spalte statt nur Ort.
- [x] Badges: erneut angefragt / Kontakt bekannt / Telefon prüfen / Adresse mehrdeutig, plus anklickbare Verweise mit richtungseindeutigem Text ("Veraltet – aktuelle Version vom X" / "Aktuelle Version – frühere Anfrage vom X") zum jeweils verwandten Lead. duplikat/ersetzt/spam/ausland-Zeilen zusätzlich als ganze Zeile gedämpft (`row-inaktiv`), damit man die Dedup-Logik sieht statt sie zu erraten. "Version X von Y" im Status bei mehrzeiligen Vorgängen (`_fetch_vorgang_positions`, über ALLE Zeilen des Vorgangs, nicht nur die im Tab sichtbaren).
- [x] Status/Zugewiesen direkt in der Liste editierbar (Schnellbearbeitung, s. oben), Sortierung in den Spaltenüberschriften (Lead-Nr./Datum anklickbar, separate Sortierzeile entfällt).
- [x] Detailansicht: alle Felder (auch leere), message prominent, superseded-Kette rückwärts aufgelöst + Banner bei duplicate_of/superseded_by, Event-Historie über die GANZE Kette (nicht nur den aktuellen Datensatz, inkl. lesbarem Feld-Diff bei F3), Google-Maps-Link (klickbar, war zuvor reiner Text), Kandidatenliste bei mehrdeutig (Block d), Mail-Status-Zeile, Aktionen inkl. Geocoding-Wiederholung. Route `GET /admin/leads/{lead_id}`, verlinkt aus der Liste.
- [x] Aktionen: Status ändern (nur die 5 manuell sinnvollen Werte, s. `_MANUALLY_SETTABLE_STATUSES`; `disqualifiziert` verlangt einen Grund), assigned_to, disqualify_reason als ein Formular (`POST /admin/leads/{id}/bearbeitung`), "Mail erneut senden" einzeln, "Geocoding wiederholen" einzeln (Block d), globaler Retry-Button (Block d). Status-Wechsel synct is_spam mit (Konzept §J), setzt contacted_at automatisch, schreibt Events, aktualisiert traffic_light (Block c).
- [x] CSV: `GET /admin/export.csv`, Semikolon, UTF-8 BOM (`utf-8-sig`), Europe/Berlin, deutsche Header. Läuft über dieselben `_fetch_leads`/`_decorate_row` wie die Liste, damit Filter/Suche/Sortierung nie auseinanderlaufen können. **Noch nicht in Excel geöffnet.**
- [x] Tab Auswertung (`GET /admin/auswertung`): GROUP BY channel/campaign/heard_about/Bundesland, alle 8 Spalten aus §7, "Basis: n" pro Zeile, Quoten unter n=10 grau/kursiv, Kreuztabelle Kanal×Bundesland. Live gegen echte Daten verifiziert.
- [x] Spaltenfilter (Ort/Bundesland/Ampel/Kanal/Status/Zugewiesen) statt der zwei ursprünglichen Dropdowns, aus tatsächlich vorhandenen DB-Werten (`_distinct_values`), Ampel-Filter läuft seit Block c als echtes SQL.

## Phase 4 — Geocoding — vollständig ✅
- [x] **Block (a):** Nominatim-Client, zweigeteilt: `app/core/geocoding.py` (reine Auswertung, testbar ohne Netzwerk) + `app/geocoding.py` (echter Client). Status ok/mehrdeutig/nicht_gefunden/fehlgeschlagen (zusätzlich nur_ort/plz_abweichend, s. oben - `countrycodes=de` entfernt). Mehrdeutig-Kriterium: Bundesland+Gemeinde-Übereinstimmung (nicht rohe Trefferzahl), `importance`-Tie-Breaker, Auswahl-Protokoll in `geocode_raw.auswahl`. Stadtstaaten-Fallback über ISO-3166-2-lvl4 (Berlin/Hamburg fehlt das `state`-Feld bei Nominatim, Bremen nicht durchgängig), `geo_state_unresolved`-Flag macht ein unauflösbares Bundesland sichtbar statt still `None`.
- [x] **Block (b):** `POST /admin/retry` (`app/retry.py` + Route in `app/admin.py`), Session-Cookie ODER `X-Retry-Secret`-Header. Filtert immer auf `process_after <= now()`, für Geocoding UND Mail auf `status IN ('offen','fehlgeschlagen')`. `MAX_GEOCODE_PER_MINUTE` (Ratenbremse, usage_counters) getrennt von `GEOCODE_BATCH_SIZE` (Portionsgröße pro Aufruf, Default 5), 1.1s Pause zwischen Nominatim-Anfragen. Antwort meldet `verarbeitet` UND `verbleibend` getrennt für Geocoding/Mail/Auslandshinweis. DRY_RUN_GEOCODE spiegelt DRY_RUN_EMAIL. F3-Korrektur setzt Vorgänger auf `geocode_status='entfaellt'` nur wenn dessen Geocoding noch offen/fehlgeschlagen war.
- [x] **Block (c):** `traffic_light`/`traffic_light_reason` werden bei jedem Schreibvorgang berechnet statt live beim Lesen. `app/traffic_light.py::apply_traffic_light(conn, lead_id)` einziger Ort, der `app/core/ampel.py` mit einem DB-Read/Write verbindet. Alle ampel-relevanten Schreibpfade angeschlossen.
- [x] **Block (d):** Kandidaten bei `geocode_status='mehrdeutig'` in der Detailansicht, Button "Geocoding wiederholen" je Lead, globaler Retry-Button in der Liste.
- [x] **Block (e):** `.github/workflows/retry-cron.yml`, alle 15 Minuten + `workflow_dispatch`. `RETRY_URL`/`RETRY_SECRET` in GitHub gesetzt, manuell ausgelöst - **lief grün, Endpunkt erreicht.**
- [x] Auslandspfad (Konzept §A): zweite Mail, `status='ausland'`, `expansion_opt_in` - vollständig gebaut, live verifiziert (s. "Geocoding: aktueller technischer Stand" oben für den finalen, korrigierten Stand).
- [x] Bundesland→Landesbauordnung-Mapping (Konzept §C) bewusst gestrichen (kein Bauauftrag, keine externe Schnittstelle, s. oben).
- [x] Geocoding-Untersuchung + Ortsebene-Rückfall + Auslandserkennung über country_code + PLZ-Abweichung: s. "Geocoding: aktueller technischer Stand" oben, ausführlich in docs/FUNDE.md.

## Phase 5 — Abnahme ✅ weitgehend
- [x] Fünf Beispielanfragen vom Handy (fiktive Mails, einmal mit ?utm_source=meta&utm_campaign=test)
- [x] #1/#4: F2 oder F3 korrekt? **Tatsächliches Ergebnis weicht vom hier ursprünglich erwarteten ab:** Die Duplikat-/Korrektur-Testreihe (Ahrens, lead_nummer 4) lief live über drei echte Submits statt einer einfachen Zwei-Wege-Dopplung - live gegen die Datenbank geprüft. Schritt 1→2 änderte tatsächlich `phone_raw` UND `heard_about`, Schritt 2→3 zusätzlich noch etwas, das den content_hash veränderte, obwohl der Feld-Diff dafür leer aussieht - beide Schritte liefen deshalb als **F3** (Korrektur, dreistufige `superseded_by`-Kette), nicht als F2, wie die ursprüngliche Erwartung hier annahm. Ergebnis inhaltlich korrekt (Diff sichtbar, Vorgänger ausgegraut, Nummer vererbt), nur die Klassifikation F2 traf nicht zu - in den aktuellen Demo-Daten existiert aktuell **kein** F2-Fall (`status='duplikat'` kommt in keiner der zehn Zeilen vor).
- [x] #2: ambiguous, Kandidaten sichtbar, in_service_area null/grau — **Achtung, abweichend vom ursprünglichen Plan:** "Lindenweg 3, Neustadt" ohne PLZ ergibt jetzt bewusst nicht_gefunden statt mehrdeutig (s. oben) - dieser Prüfpunkt braucht ggf. eine andere Testadresse, wenn eine echte mehrdeutige Ampel gezeigt werden soll.
- [x] Ampel: Testadresse in Österreich → rot + Auslandsmail — **Achtung:** PLZ-Format-Validierung akzeptiert keine 4-stelligen (österreichischen) PLZ, s. offener Fund oben - PLZ ggf. weglassen.
- [x] Lead ohne Telefon -> gelb "Nur per E-Mail erreichbar"
- [ ] Korrekturfenster: Lead absenden, innerhalb 1h korrigierten Antrag schicken -> nur der neue wird geokodiert, alter auf entfaellt — **nicht bestätigt:** kein expliziter manueller Test dieses genauen Ablaufs; die Ahrens-Korrekturkette lief zwar vollständig innerhalb des 1h-Fensters ab (alle drei Submits binnen 5 Minuten), das prüft aber nicht gezielt, ob process_after/entfaellt korrekt gesetzt wird.
- [ ] Korrektur-Link aus Mail oeffnen: Formular vorbefuellt, ein Feld aendern, absenden -> F3 greift — nicht bestätigt.
- [ ] Namens-Normalisierung: TOM AHRENS -> Tom Ahrens, mcdonald bleibt bei gemischter Schreibweise unangetastet — nicht Teil dieser manuellen Abnahme; separat über pytest und `scripts/testlauf.py` (docs/TESTLAUF.md) live abgedeckt.
- [x] Honeypot-Submit und Submit nach 1 Sekunde -> is_spam, keine Mail, im Spam-Filter sichtbar — **Honeypot bestätigt**, die Zeitschwellen-Variante (Submit < 3s) nicht gesondert genannt.
- [ ] Kanal-Ableitung: einmal mit gclid, einmal mit fbclid, einmal ohne Parameter -> channel und channel_source korrekt — nicht bestätigt.
- [ ] F3-Test A: korrigierte Telefonnummer → neuer führt, alter ausgegraut, Diff im Event (lesbar in der Detailansicht, s. oben), Status vererbt — nicht als eigener Testschritt bestätigt (die Ahrens-Kette oben zeigt eine Telefonkorrektur, aber ohne vorherigen Statuswechsel, die Vererbung eines NICHT-Default-Status wurde damit nicht gezeigt).
- [ ] F3-Test B: zweiter Submit MIT weniger Feldern → Merge füllt Lücken aus altem Datensatz, nichts geht verloren — nicht bestätigt.
- [ ] F4-Test: gleiche Person, zweites Grundstück → zwei aktive, Badge — **nicht bestätigt, per DB verifiziert:** kein `kontakt_bekannt`-Event existiert aktuell in den Demo-Daten, der Fall wurde also nicht durchgespielt.
- [x] Pflichtfeld-Reject (nur Adresse/E-Mail/Datenschutz): Eingaben bleiben stehen
- [x] Lead ohne Telefonnummer: Badge "nur E-Mail", Ampel gelb, Mail geht raus
- [x] Doppelklick, Reload auf POST, Honeypot, Brevo-Key falsch → failed → Retry heilt
- [x] Umlaute end-to-end inkl. Excel-Öffnung; Mail-Zusammenfassung stimmt; Handy-Check
- [x] Status/Zugewiesen per Inline-Bearbeitung in der Liste ändern (inkl. disqualifiziert mit Pflicht-Grund), Zeile verlässt den Filter sichtbar statt kommentarlos

## Phase 6 — Notizen & Abgabe
- [x] NOTES.md: Entscheidungen+Begründung (K1-K6 Material) / offen / nächste Schritte bei Livegang (Edit-Link, Offline-Conversions, A/B Formularlänge, Rückrufwunsch) / Schwächen ehrlich — **dabei einbeziehen:** Landesbauordnung-Streichung (Begründung s. oben), PLZ-Validierungsfund, der Zwischenfall mit dem überschriebenen Beispiel-Lead als Beleg für sorgfältiges Vorgehen (gefunden, sofort gestoppt, vollständig wiederhergestellt, Ursache behoben statt nur das Symptom)
- [ ] README kurz; Notizen als 1-Seiten-PDF — NOTES.md-Inhalt steht, README und PDF-Format nicht bestätigt.
- [x] Repo-Hygiene: keine Secrets, Historie sauber
- [ ] Abgabe vorbereiten — offen: Repo auf öffentlich stellen, Abgabe-Mail.
