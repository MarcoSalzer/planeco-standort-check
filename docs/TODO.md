# Standort-Check: To-do (v2)

Abgabe: Do 20.08. 10:00 an Tessa, CC Björn + Basti. Interview: Fr 21.08. 10:00.
Fenster: Fr 14.08. mittags bis Mi 19.08. abends. Mi ist Puffer.

## Stand 18.08. — Übergabe für eine frische Session

Diese Session lief voll. Der Abschnitt hier ersetzt die bisherigen,
über mehrere Tage angehäuften "Stand"-Absätze (die standen vorher direkt
unter diesem Titel, jetzt Verlaufsmaterial in den Phasen-Checklisten
unten) durch eine einzige, aktuelle Zusammenfassung. Wer hier neu
einsteigt, braucht NICHT den bisherigen Gesprächsverlauf - alles
Nötige steht in diesem Abschnitt plus `docs/KONZEPT.md` (Fachlogik),
`docs/FUNDE.md` (Implementierungsfunde mit Ursache) und `CLAUDE.md`
(harte Regeln). Die Phasen-Checklisten weiter unten (ab "## Phase 0")
bleiben als detailliertes Verlaufsmaterial stehen, auch was hier oben
schon knapper zusammengefasst ist - für NOTES.md (Phase 6) nützlich,
für den Einstieg nicht nötig.

### Was fertig ist

**Phase 0-3 vollständig** (Konzept final, Formular + Submit-Pfad inkl.
Dedup F1-F4/Spam-Erkennung/Korrektur-Link, komplettes Dashboard mit
Login/Liste/Detailansicht/Aktionen/CSV-Export/Auswertungs-Tab). Details
in den jeweiligen Phasen-Checklisten unten, dort auch die Live-Tests.

**Phase 4 (Geocoding), Block (a)-(e) vollständig:**
- (a) Nominatim-Client (`app/geocoding.py` + reine Auswertung in
  `app/core/geocoding.py`) - strukturierte Abfrage, Mehrdeutig-Kriterium
  über Bundesland+Gemeinde-Übereinstimmung (nicht rohe Trefferzahl),
  Stadtstaaten-Fallback über ISO-3166-2.
- (b) `POST /admin/retry` (`app/retry.py`), verarbeitet offenes Geocoding
  und fehlgeschlagene Mails, `RETRY_SECRET`-Header ODER Admin-Session,
  `GEOCODE_BATCH_SIZE` als Portionsgröße getrennt von der
  `MAX_GEOCODE_PER_MINUTE`-Ratenbremse.
- (c) `traffic_light`/`traffic_light_reason` werden bei jedem
  Schreibvorgang berechnet (`app/traffic_light.py::apply_traffic_light`),
  nicht mehr live beim Lesen - alle ampel-relevanten Schreibpfade
  angeschlossen (Submit, Geocoding-Ergebnis, manueller Statuswechsel,
  Spam-Freigabe, F3-Korrektur).
- (d) Kandidatenliste bei mehrdeutigen Adressen in der Detailansicht,
  Button "Geocoding wiederholen" je Lead, globaler Retry-Button in der
  Liste mit Live-Anzeige von verarbeitet/verbleibend.
- (e) `.github/workflows/retry-cron.yml`, alle 15 Minuten, braucht
  `RETRY_URL`/`RETRY_SECRET` in den GitHub-Repo-Einstellungen (Settings >
  Secrets and variables > Actions) - **noch nicht live getestet**, s.
  "Nächste Schritte" unten.

**Zwei Dashboard-Korrekturrunden nach Block (e)** (Details in der
Phase-4-Checkliste unten, jeweils datiert): 17.08. - Zeilen-Isolierung
(eine defekte Zeile stürzt nicht mehr die ganze Liste ab), Spaltenfilter
statt der zwei alten Dropdowns. 18.08. - Gruppen-Einfärbung nach
Lead-Nummer wieder entfernt (war im Standardfilter bedeutungslos, s.
docs/FUNDE.md), Tab "Alle" zeigt inaktive Zeilen jetzt standardmäßig,
Lead-Nummer als eigene an/absteigende Sortierung, kompakte Ampel-Legende.

**Deploy-Fix (17.08.):** `pyproject.toml` brach den Vercel-Build (Datei
existierte nur für Pytest-Konfiguration, wurde von Vercels `uv`-Build
aber als Projektdefinition gelesen). Behoben durch Entfernen der Datei
(Pytest-Konfiguration jetzt in `pytest.ini`) statt einen `[project]`-
Abschnitt nachzutragen - Letzteres hätte riskiert, dass Vercel
`requirements.txt` künftig ignoriert. Details + Abwägung in
docs/FUNDE.md. **Alle Commits sind bei `origin/main` gepusht** (`git
status` zeigt "up to date"), aber der Fix wurde noch NICHT gegen einen
echten Vercel-Build verifiziert - unbekannt, ob der Build inzwischen
durchläuft.

### Aktueller Modul-Stand (`app/`)

- `main.py` — Formular-Routen (`/`, `/datenschutz`, `/danke`), `POST
  /submit` (Orchestrierung: Validierung → Normalisierung → Dedup → Mail
  → Redirect). `load_dotenv()`/`logging.basicConfig()` laufen vor allen
  `app.*`-Imports (s. docs/FUNDE.md).
- `admin.py` — Login/Logout, Lead-Liste (`GET /admin`, Tabs/Suche/
  sechs Spaltenfilter/Sortierung), Detailansicht (`GET
  /admin/leads/{id}`), Aktionen (Statuswechsel, Mail-Resend, Geocoding-
  Wiederholung je Lead), CSV-Export, Auswertungs-Tab, `POST
  /admin/retry`-Route (Auth) und `POST
  /admin/leads/{id}/geocoding-wiederholen`.
- `submission.py` — `persist_submission()` (Dedup-Entscheidung F1-F4 aus
  `app.core.dedup` anwenden, INSERT/UPDATE + Events, eine Transaktion),
  `row_to_new_lead_data()` (für Mail-Resend/Retry gemeinsam genutzt).
- `mail.py` — `send_confirmation_email()`, gibt seit Block (b) den
  resultierenden `email_status` zurück.
- `geocoding.py` — Nominatim-HTTP-Client, `SERVICE_AREA_STATES` wird
  beim Modul-Import validiert (fail fast bei unbekanntem Bundesland-
  Namen).
- `retry.py` — Retry-Orchestrierung: `run_retry()` (Batch, für Cron/
  globalen Button), `retry_one_geocode()` (Einzel-Lead, immer versucht,
  unabhängig vom aktuellen Status).
- `traffic_light.py` — `apply_traffic_light(conn, lead_id)`, einziger
  Ort, der `app.core.ampel.ampel()` mit einem DB-Read/Write verbindet.
- `db.py` — `get_connection()` (Transaction Pooler, `prepare_threshold=
  None`), `insert_event()`.
- `config.py` — Env-Konstanten, beim Modul-Import gelesen (fail fast).
- `templating.py` — gemeinsame `Jinja2Templates`-Instanz.
- `core/*` — reine Funktionen ohne DB/HTTP, je mit Tests in
  `tests/core/`: `normalize.py`, `text.py`, `content_hash.py`,
  `dedup.py`, `merge.py`, `spam.py`, `validation.py`, `channel.py`,
  `edit_token.py`, `admin_auth.py` (inkl. `verify_retry_secret`),
  `ampel.py` (Konzept §B, nur noch von `traffic_light.py` aufgerufen,
  nicht mehr beim Lesen), `display.py`, `geocoding.py` (Konzept §B/§G,
  inkl. `candidate_summaries()` für Block d).
- `templates/` — `form.html`, `danke.html`, `datenschutz.html`,
  `email_confirmation.html`, `admin_login.html`, `admin_dashboard.html`,
  `admin_lead_detail.html`, `admin_auswertung.html`.
- `scripts/` — `gen_secrets.py`, `testlauf.py` (40 systematische
  Randfälle, s. docs/TESTLAUF.md), `backfill_lead_nummer.py`,
  `backfill_traffic_light.py` (beide bereits einmalig `--apply`
  ausgeführt, Bestand ist aktuell).
- Migrationen bis `migrations/0009_geocode_candidate_count.sql`, alle
  bereits gegen die produktive Supabase-Instanz gelaufen.

### Tests

176 Tests, alle grün: `.venv/bin/python -m pytest -q`. Pytest-Konfiguration
jetzt in `pytest.ini` (nicht mehr `pyproject.toml`, s. Deploy-Fix oben).

### Nächste Schritte (von Marco vorgegeben, in dieser Reihenfolge)

1. **Sortierung in die Spaltenüberschriften verlegen.** Lead-Nummer und
   Datum werden direkt an der Spaltenüberschrift anklickbar (auf- und
   absteigend), mit sichtbarer Richtungsanzeige (z.B. Pfeil-Symbol). Die
   separaten Sortierlinks im `.sort-row` oberhalb der Tabelle
   (`admin_dashboard.html`) entfallen dafür komplett - auch "Älteste/
   Neueste zuerst" wandert an die Datums-Spaltenüberschrift.
2. **Widersprüchliche Hinweistexte bei Korrekturketten korrigieren.**
   Aktuell (`app/admin.py::_decorate_row`, Badges) steht bei der ALTEN
   Version "Ersetzt durch Anfrage vom X" (Link zur neuen) und bei der
   GÜLTIGEN Version "Frühere Version vom X" (Link zur alten) - beide
   Texte zeigen aufeinander, ohne dass am Text selbst erkennbar wäre,
   welche der beiden Zeilen die aktuell gültige ist. Formulierung so
   korrigieren, dass die Richtung (welche Version ist aktuell, welche
   überholt) direkt am Text ablesbar ist, nicht nur über Kontext/
   Dämpfung erschließbar.
3. **Google-Maps-Link direkt in die Liste.** Kleines Symbol in der
   Ort-Spalte bei Leads mit `lat`/`lon` gesetzt, verlinkt wie in der
   Detailansicht (`_field_groups`, `maps_link`) nach
   `https://maps.google.com/?q={lat},{lon}`. Ohne Koordinaten bleibt die
   Stelle leer (keine Platzhalter-Andeutung). Der bestehende Link in der
   Detailansicht bleibt zusätzlich bestehen, wird nicht ersetzt.
4. **Auslandspfad nach Konzept §A.** Eigener, größerer Baustein - nicht
   nebenbei miterledigen. Umfasst: zweite, separate Mail bei
   `in_service_area=false` (`ausland_hinweis_status`-Spalte existiert
   bereits seit Migration 0001, aber ungenutzt), `status='ausland'`
   (Status-Wert existiert bereits im CHECK-Constraint), Formularfeld
   `expansion_opt_in` (Spalte existiert bereits, aber kein Formularfeld
   dafür und keine Logik, die sie setzt oder ausliest). Rechtlich
   vorsichtige Formulierung s. Konzept §A (keine automatische
   Weitergabe an Partner, Einwilligung nur durch aktive Antwort). Vor dem
   Bauen Konzept §A nochmal vollständig lesen, nicht aus der
   Erinnerung rekonstruieren.
5. **Landesbauordnungs-Zuordnung als letzter Baustein.** Konzept §C
   ("Zweite Erweiterung: Bundesland → Landesbauordnung"). Separat NACH
   Auslandspfad, wie von Marco explizit sortiert.
6. **Offen aus früheren Runden (Konzept §D):** MX-Prüfung bei
   E-Mail-Validierung (`check_deliverability=True`, DNS-Lookup, ~100ms -
   aktuell bewusst nicht eingebaut, s. `app/core/validation.py`-
   Docstring, Begründung: Netzwerk-Aufruf würde die reine Funktion nicht
   mehr ohne Netzwerk testbar machen, müsste in `app/main.py` VOR
   `persist_submission` mit eigenem Timeout laufen). Tippfehler-Vorschlag
   für bekannte Domains (Levenshtein gegen Liste der 20 häufigsten
   Domains, "Meinten Sie gmail.com?", kein Blocker, Client-seitig JS +
   ggf. Server-Hinweis). Beides vor Abgabe bewusst entscheiden: einbauen,
   oder als Scope-Cut in NOTES.md dokumentieren.

Danach committen. Kein Punkt aus dieser Liste ist in der aktuellen
Session begonnen worden - jeder ist ein eigener, klar abgegrenzter
Baustein.

### Sonstiges, noch offen (kein Bauauftrag, nur Diese-Woche-Erinnerung)

- **Deploy + Cron-Test:** nach dem nächsten Vercel-Deploy prüfen, ob der
  Build durchläuft (Deploy-Fix oben), danach `RETRY_URL`/`RETRY_SECRET`
  in GitHub setzen und den Workflow einmal manuell über "Run workflow"
  (`workflow_dispatch`) auslösen.
- **F2-Mailtext:** enthält einen Gedankenstrich ("... vorliegenden
  Anfrage — es hat sich nichts geändert."), `app/mail.py`,
  `_INTRO_TEXT_BY_CASE[DedupCase.F2_DUPLIKAT]`. Vor Abgabe gegenlesen.
- **CSV noch nicht in Excel geöffnet** (Marco macht das selbst).
- **`app/config.py`-Docstring veraltet** ("wird von nichts importiert" -
  stimmt nicht mehr, wird inzwischen von mehreren Modulen importiert).
  Kleinkram, bei Gelegenheit korrigieren.
- Phase 5 (Abnahme) und Phase 6 (Notizen & Abgabe) unten noch komplett
  offen, wie geplant erst nach Phase 4.

## Phase 0 — Konzept fixieren (Chat) ✅ weitgehend
- [x] Datenmodell + Pipeline + Risiken (KONZEPT v2)
- [x] Review-Runde: Felder, Duplikat-Semantik, Mail-Regel, Konflikte K1-K6
- [x] Review 2: Pflichtfelder, Ampel, Feld-Merge, Auswertungs-Tab, deutsche Statuswerte
- [x] Review 3: Auslandspfad, Ampelregeln, Bundesland-Mapping, E-Mail-Prüfung, Mail-Ausnahmen
- [x] Review 4: Korrekturfenster 1h, Kanal-Ableitung, Namens-Normalisierung, Spam-Muster, Kontakt im Footer
- [ ] Nur noch offen: nichts. Konzept ist final.

## Phase 1 — Accounts & Skelett (Fr, ~2-3h) ✅
- [x] Accounts nach SETUP.md Schritt 1: Brevo zuerst (Verifizierung!), dann Supabase, Vercel, GitHub
- [x] Lokaler Ordner + git init + docs/ (SETUP.md Schritt 2), CLAUDE.md ins Wurzelverzeichnis
- [x] Repo `planeco-standort-check` (public), .env.example, attribution-Setting
- [x] FastAPI-Skelett deployed auf Vercel, URL erreichbar
- [x] Schema v2 in Supabase (leads + lead_events), Testzeile schreiben/lesen
- [x] Env-Variablen bei Vercel
- **Abbruchkriterium:** läuft das Fr abend nicht → Sa früh Ursache klären, nicht auf wackligem Deploy weiterbauen

## Phase 2 — Kernpfad (Sa, ~4-5h) ✅
- [x] Formular mit Feldliste §3.1 v3 (nur Adresse+E-Mail+Datenschutz Pflicht, Rest optional markiert)
- [x] Hidden Fields: utm_*, gclid, fbclid, referrer, landing_page, token, rendered_at, Honeypot
- [x] POST /submit: Server-Validierung (422 re-rendert MIT Eingaben), Normalisierung, content_hash, Dedup-Entscheidung F1-F4, INSERT, PRG
- [x] F3 Feld-Merge (neu gewinnt bei Konflikt, alt füllt Lücken) + superseded-Kette + Events mit changed_fields/merged_fields
- [x] E-Mail-Validierung: Client type=email + JS-Tippfehlervorschlag; Server Syntax (email-validator) — **MX-Prüfung bewusst ausgelassen, s. "Nächste Schritte" Punkt 6 oben**
- [x] Namens-Normalisierung (nur bei durchgaengig GROSS/klein), name_raw erhalten, Tabellentest inkl. McDonald/van der Berg/Mueller-Luedenscheidt
- [x] Kanal-Ableitung beim INSERT: channel + channel_source nach Prioritaetsliste, Tabellentest
- [x] process_after setzen (Env PROCESS_DELAY_MINUTES) — mit Phase 4 Block (c) verdrahtet, s. docs/FUNDE.md
- [x] Kontakthinweis im Formular-Footer und auf Fehlerseiten (Env-Variablen)
- [x] Bestätigungsmail: HTML-Template (Datenzusammenfassung, Korrektur-Hinweis, Erwartung, Kontaktblock), best effort, Statusfelder
- [x] Mail-Ausnahmen: nur F1 und Spam bekommen keine Mail (Konzept §E)
- [x] Korrektur-Link mit Vorbefuellung: signiertes Token (itsdangerous, 7 Tage), GET /?k=... befuellt Formular, kein Schreibzugriff
- [x] Spam-Erkennung: Honeypot, Zeitschwelle, Link-Zaehler im message-Feld, Zeichensatz-Heuristik
- [x] pytest: normalize_phone (5 Beispielformate), content_hash-Stabilität, dedup_decision F1-F4, merge_fields (neu/leer/beide leer)

## Phase 3 — Dashboard (So, ~3-4h) ✅
- [x] Login (Env-Credentials, signierter Cookie, constant-time) — vom Nutzer live getestet, funktioniert
- [x] Tabs Neu/In Bearbeitung/Erledigt/Alle; duplicate/superseded/spam/ausland in Neu/Bearbeitung/Erledigt default aus (Toggle "alles anzeigen"), in Alle seit 18.08. umgekehrt default AN (Toggle blendet aus)
- [x] Spalten inkl. Bundesland, Ampel (traffic_light, seit Block c bei jedem Schreibvorgang berechnet statt live), Kanal (channel + heard_about getrennt) — Beschriftungen durchgängig deutsch, Volltextsuche über Name/E-Mail/Telefon/Ort, Leerzustand mit Meldung statt leerer Tabelle. Vom Nutzer im Browser getestet, funktioniert.
- [x] Badges: erneut angefragt / Kontakt bekannt / Telefon prüfen / Adresse mehrdeutig, plus anklickbare Verweise ("Duplikat von Anfrage vom X" / "Ersetzt durch Anfrage vom X" / "Frühere Version vom X") zum jeweils verwandten Lead — **Hinweistexte bei Ketten widersprüchlich/richtungslos, s. "Nächste Schritte" Punkt 2 oben**. duplikat/ersetzt/spam/ausland-Zeilen zusätzlich als ganze Zeile gedämpft (`row-inaktiv`), damit man die Dedup-Logik sieht statt sie zu erraten. "Version X von Y" im Status bei mehrzeiligen Vorgängen (`_fetch_vorgang_positions`, über ALLE Zeilen des Vorgangs, nicht nur die im Tab sichtbaren).
- [x] Detailansicht: alle Felder (auch leere), message prominent, superseded-Kette rückwärts aufgelöst + Banner bei duplicate_of/superseded_by, Event-Historie über die GANZE Kette (nicht nur den aktuellen Datensatz), Google-Maps-Link, Kandidatenliste bei mehrdeutig (Block d), Aktionen inkl. Geocoding-Wiederholung. Route `GET /admin/leads/{lead_id}`, verlinkt aus der Liste.
- [x] Aktionen: Status ändern (nur die 5 manuell sinnvollen Werte, s. `_MANUALLY_SETTABLE_STATUSES`), assigned_to, disqualify_reason als ein Formular (`POST /admin/leads/{id}/bearbeitung`), "Mail erneut senden" einzeln, "Geocoding wiederholen" einzeln (Block d), globaler Retry-Button (Block d). Status-Wechsel synct is_spam mit (Konzept §J), setzt contacted_at automatisch, schreibt Events, aktualisiert traffic_light (Block c).
- [x] CSV: `GET /admin/export.csv`, Semikolon, UTF-8 BOM (`utf-8-sig`), Europe/Berlin, deutsche Header. Läuft über dieselben `_fetch_leads`/`_decorate_row` wie die Liste, damit Filter/Suche/Sortierung nie auseinanderlaufen können. **Noch nicht in Excel geöffnet** - das macht Marco selbst.
- [x] Tab Auswertung (`GET /admin/auswertung`): GROUP BY channel/campaign/heard_about/Bundesland, alle 8 Spalten aus §7, "Basis: n" pro Zeile, Quoten unter n=10 grau/kursiv, Kreuztabelle Kanal×Bundesland. Live gegen echte Daten verifiziert.
- [x] Spaltenfilter (Ort/Bundesland/Ampel/Kanal/Status/Zugewiesen) statt der zwei ursprünglichen Dropdowns, aus tatsächlich vorhandenen DB-Werten (`_distinct_values`), Ampel-Filter läuft seit Block c als echtes SQL. **Sortierung wandert als nächstes ebenfalls in die Spaltenüberschriften, s. "Nächste Schritte" Punkt 1 oben.**

## Phase 4 — Geocoding (Mo, ~2-3h) — Block (a)-(e) fertig ✅
- [x] **Block (a):** Nominatim-Client, zweigeteilt: `app/core/geocoding.py` (reine Auswertung, testbar ohne Netzwerk) + `app/geocoding.py` (echter Client: structured query street/city/postalcode getrennt, countrycodes=de, limit=5, format=jsonv2, addressdetails=1, User-Agent aus NOMINATIM_USER_AGENT-Env, Timeout 3s). Status ok/mehrdeutig/nicht_gefunden/fehlgeschlagen. Mehrdeutig-Kriterium: Bundesland+Gemeinde-Übereinstimmung (nicht rohe Trefferzahl), `importance`-Tie-Breaker, Auswahl-Protokoll in `geocode_raw.auswahl`. Stadtstaaten-Fallback über ISO-3166-2-lvl4 (Berlin/Hamburg fehlt das `state`-Feld bei Nominatim, Bremen nicht durchgängig), `geo_state_unresolved`-Flag macht ein unauflösbares Bundesland sichtbar statt still `None`. Drei Funde dabei in docs/FUNDE.md (Mehrdeutig-Kriterium selbst, Stadtstaaten, `SERVICE_AREA_STATES=alle` wurde nicht erkannt).
- [x] **Block (b):** `POST /admin/retry` (`app/retry.py` + Route in `app/admin.py`), Session-Cookie ODER `X-Retry-Secret`-Header. Filtert immer auf `process_after <= now()`, für Geocoding UND Mail auf `status IN ('offen','fehlgeschlagen')`. `MAX_GEOCODE_PER_MINUTE` (Ratenbremse, usage_counters) getrennt von `GEOCODE_BATCH_SIZE` (Portionsgröße pro Aufruf, Default 5), 1.1s Pause zwischen Nominatim-Anfragen. Antwort meldet `verarbeitet` UND `verbleibend` getrennt für Geocoding/Mail. DRY_RUN_GEOCODE spiegelt DRY_RUN_EMAIL (→ `geocode_status='simuliert'`, Migration 0007). `geo_state_unresolved` (Migration 0008) wird persistiert. F3-Korrektur setzt Vorgänger auf `geocode_status='entfaellt'` nur wenn dessen Geocoding noch offen/fehlgeschlagen war. `PROCESS_DELAY_MINUTES` zusätzlich verdrahtet (war dokumentiert, aber wirkungslos, s. docs/FUNDE.md).
- [x] **17.08., Dashboard-Korrektur nach einem 500er:** `geocode_status='simuliert'` fehlte in `app/core/ampel.py` (wirft bei jedem unbekannten Wert bewusst, CLAUDE.md Regel 3) - ein einzelner betroffener Lead riss die GANZE Liste ab, weil `ampel()` ungeschützt in einer Schleife über alle Zeilen lief. Behoben: Zeilen-Isolierung (`_decorate_row_safe()`, defekte Zeile bekommt eigenen Ampel-Status "defekt" statt die Liste zu zerstören), plus bei derselben Gelegenheit: Sortierung/Gruppierung nach Vorgang (später am 18.08. korrigiert, s.u.), Spaltenfilter (s. Phase 3 oben).
- [x] **Block (c):** `traffic_light`/`traffic_light_reason` (Spalten seit Migration 0001, nie befüllt) werden bei jedem Schreibvorgang berechnet statt live beim Lesen. `app/traffic_light.py::apply_traffic_light(conn, lead_id)` einziger Ort, der `app/core/ampel.py` (bleibt reine Funktion) mit einem DB-Read/Write verbindet. Alle fünf ampel-relevanten Schreibpfade angeschlossen: Submit (`_insert_lead`), Geocoding-Ergebnis (alle drei Fälle in `app/retry.py`), manueller Statuswechsel UND Spam-Freigabe (ein unbedingter Aufruf in `update_lead_bearbeitung`, nicht an einzelne Feldnamen gebunden), F3-Korrektur (`_supersede()`, Ampel des VORGÄNGERS). Neue Spalte `geocode_candidate_count` (Migration 0009). Bestand per `scripts/backfill_traffic_light.py --apply` nachgerechnet, 32/32 Zeilen. Liste/Detailansicht lesen nur noch `row["traffic_light"]`. Ampel-Filter läuft seither als echtes SQL statt Python-Nachfilterung.
- [x] **Block (d):** Kandidaten bei `geocode_status='mehrdeutig'` in der Detailansicht (`candidate_summaries()` in `app/core/geocoding.py`, aus bereits gespeichertem `geocode_raw`, kein neuer API-Aufruf) - live mit dem "Lindenweg 3, Neustadt"-Testfall verifiziert. Button "Geocoding wiederholen" je Lead (`retry_one_geocode()`, immer versucht, respektiert aber weiterhin Kontingent/DRY_RUN). Globaler Retry-Button in der Liste (`fetch()`, zeigt verarbeitet/verbleibend direkt an).
- [x] **18.08., Korrektur nach Marcos Export-Analyse (überholt die "Blockweise Tönung" vom 17.08.):** Gruppen-Einfärbung entfernt - im Standardfilter bestand jede Lead-Nummer-Gruppe ohnehin nur aus einer Zeile, die Farbe war ein bedeutungsloses Zebramuster in einer Farbe (Blau), die wie eine Hervorhebung liest statt wie eine Dämpfung (Fund in docs/FUNDE.md). Ersetzt durch die bereits vorhandene `row-inaktiv`-Regel allein. Tab "Alle" zeigt inaktive Zeilen jetzt standardmäßig (Tab heißt "Alle"), Schalter blendet dort aus statt ein. Lead-Nummer als eigene, in beide Richtungen anklickbare Sortierung (`nummer_auf`/`nummer_ab`), ersetzt den überflüssig gewordenen "vorgang"-Sondermodus. Kompakte einzeilige Ampel-Legende über der Liste. Live geprüft: Nummern 6/12/14/15/17 stehen nach Lead-Nummer sortiert direkt untereinander, exakt eine normal dargestellte Zeile pro Gruppe.
- [x] **Block (e):** `.github/workflows/retry-cron.yml`, `schedule: */15 * * * *` + `workflow_dispatch`. `curl -sS --fail` gegen `${{ vars.RETRY_URL }}/admin/retry` mit `X-Retry-Secret`-Header. Braucht `RETRY_URL`(Variable)/`RETRY_SECRET`(Secret) in den GitHub-Repo-Einstellungen. YAML-Syntax lokal geprüft, **noch nicht live gegen ein Deployment getestet**.
- [ ] Auslandspfad (Konzept §A) und Bundesland→Landesbauordnung-Mapping (Konzept §C): s. "Nächste Schritte" Punkt 4/5 oben, mit genauerer Beschreibung als hier.

## Phase 5 — Abnahme (Di, ~2-3h)
- [ ] Fünf Beispielanfragen vom Handy (fiktive Mails, einmal mit ?utm_source=meta&utm_campaign=test)
- [ ] #1/#4: F2 oder F3 korrekt? (identisch → duplicate; hier: gleiche Inhalte, andere Telefonschreibweise → Hash gleich nach Normalisierung → F2, Original führt, Badge)
- [ ] #2: ambiguous, Kandidaten sichtbar, in_service_area null/grau
- [ ] Ampel: #2 gelb (mehrdeutig), Rest grün; Testadresse in Österreich → rot + Auslandsmail
- [ ] Lead ohne Telefon -> gelb "Nur per E-Mail erreichbar"
- [ ] Korrekturfenster: Lead absenden, innerhalb 1h korrigierten Antrag schicken -> nur der neue wird geokodiert, alter auf entfaellt
- [ ] Korrektur-Link aus Mail oeffnen: Formular vorbefuellt, ein Feld aendern, absenden -> F3 greift
- [ ] Namens-Normalisierung: TOM AHRENS -> Tom Ahrens, mcdonald bleibt bei gemischter Schreibweise unangetastet
- [ ] Honeypot-Submit und Submit nach 1 Sekunde -> is_spam, keine Mail, im Spam-Filter sichtbar
- [ ] Kanal-Ableitung: einmal mit gclid, einmal mit fbclid, einmal ohne Parameter -> channel und channel_source korrekt
- [ ] F3-Test A: korrigierte Telefonnummer → neuer führt, alter ausgegraut, Diff im Event, Status vererbt
- [ ] F3-Test B: zweiter Submit MIT weniger Feldern → Merge füllt Lücken aus altem Datensatz, nichts geht verloren
- [ ] F4-Test: gleiche Person, zweites Grundstück → zwei aktive, Badge
- [ ] Pflichtfeld-Reject (nur Adresse/E-Mail/Datenschutz): Eingaben bleiben stehen
- [ ] Lead ohne Telefonnummer: Badge "nur E-Mail", Ampel gelb, Mail geht raus
- [ ] Doppelklick, Reload auf POST, Honeypot, Brevo-Key falsch → failed → Retry heilt
- [ ] Umlaute end-to-end inkl. Excel-Öffnung; Mail-Zusammenfassung stimmt; Handy-Check

## Phase 6 — Notizen & Abgabe (Mi, ~2h)
- [ ] NOTES.md: Entscheidungen+Begründung (K1-K6 Material) / offen / nächste Schritte bei Livegang (Edit-Link, Offline-Conversions, A/B Formularlänge, Rückrufwunsch) / Schwächen ehrlich
- [ ] README kurz; Notizen als 1-Seiten-PDF
- [ ] Repo-Hygiene: keine Secrets, Historie sauber
- [ ] Abgabe-Mail Mi abend fertig, Do 09:00 senden; Do früh Erreichbarkeits-Check

## Parallel (nicht Case)
- [ ] 16Personalities neu, Ergebnis an Tessa
- [ ] Virtue Matrix: Inhalt in Chat kopieren → Rating + Sätze
- [ ] Interview-Prep: jede NOTES-Entscheidung mündlich begründbar
