# Standort-Check: To-do (v2)

Abgabe: Do 20.08. 10:00 an Tessa, CC Björn + Basti. Interview: Fr 21.08. 10:00.
Fenster: Fr 14.08. mittags bis Mi 19.08. abends. Mi ist Puffer.

## Stand 16.08. abends (8) — für den Einstieg in eine neue Session

Phase 1, Phase 2 UND Phase 3 sind vollständig fertig und committet (siehe
`git log`). Marco hat sechs echte Testanfragen über das Formular im
Browser durchlaufen lassen (u.a. "Kai Ruthenberg", "Jörg Klöpper" - Jörg
hat dabei real eine F3-Korrektur ausgelöst) und danach das komplette
Dashboard im Browser durchgeklickt - beides funktioniert. Zwei weitere
Nacharbeitsrunden folgten (alle committet):

**Runde 1 (7 Punkte):** Formular-Feldreihenfolge; heard_about-Fund
repariert (unbekannter Wert -> "keine Angabe" + Event
`unerwarteter_feldwert`, kein 422); Attributionsfelder-Fund repariert
(leer -> NULL, Migration 0005); beide Funde in docs/FUNDE.md; Sortierung
mit Tab-eigenen Defaults (Neu/Bearbeitung älteste zuerst, Erledigt/Alle
neueste zuerst) sichtbar beschriftet und umschaltbar; Zusammengehörigkeits-
Badges "Teil einer Korrekturkette/Duplikatgruppe: Anfrage X von Y"; zwei
Dropdown-Filter (Kanal, Bundesland).

**Runde 2 (3 Punkte, 2 davon umgesetzt):**
1. Formularmarkierung: nur die 3 Pflichtfelder (Adresse/E-Mail/
   Datenschutz) tragen noch ein Sternchen, "(optional)" ist überall weg,
   Nutzenhinweise (z.B. Telefon "für schnellere Rückmeldung") bleiben
   ohne das Wort "optional".
2. Lead-Nummer: fortlaufende, menschenlesbare Nummer PRO VORGANG (nicht
   pro Zeile) über `lead_nummer_seq` (Migration 0006). NEU/F4 verbrauchen
   eine neue Nummer, F2/F3 erben `candidate.lead_nummer`
   (`app/submission.py`). Bestand mit `scripts/backfill_lead_nummer.py`
   nachnummeriert - Union-Find über duplicate_of UND superseded_by
   gemeinsam, weil ein Vorgang beide Kantentypen gemischt haben kann
   (live gefunden: ein 5-zeiliger Cluster aus einer 3-stufigen
   Korrekturkette PLUS zwei F2-Duplikaten am ersten Glied). Sichtbar in
   Liste (erste Spalte), Detailansicht ("Lead #N") und CSV (erste
   Spalte). 19/19 Bestandszeilen erfolgreich nummeriert, live verifiziert
   über alle vier Dedup-Fälle.
3. **Nicht jetzt** (Marco: "nach Phase 4"): Kanal-/Bundesland-Dropdowns
   durch Spalten-Header-Filter ersetzen - als Punkt in der Phase-3-
   Checkliste unten vermerkt, nicht gebaut.

**Phase 4, Block (a) UND (b) sind fertig** (Nominatim-Client + Retry-
Endpoint, s. Checkliste unten). Die beim ersten Live-Test von Block (a)
aufgefallene "mehrdeutig"-Häufung wurde vor Block (b) untersucht und
behoben, wie von Marco verlangt ("halt nach jedem Block an" - Block (a)
wurde dafür nochmal geöffnet, nicht übersprungen). Block (b) lief
anschließend mit Marcos ausdrücklicher Freigabe inkl. einer Abweichung von
Marcos eigenem Vorschlag bei der Portionsgröße (s. Block-(b)-Eintrag
unten: `GEOCODE_BATCH_SIZE` statt höherem `maxDuration`).

**Danach, noch vor Block (c): Marco meldete einen 500er im Dashboard**
(`geocode_status='simuliert'` fehlte in `app/core/ampel.py`). Vier Punkte
umgesetzt und live verifiziert - Details im neuen Eintrag zwischen Block
(b) und (c) unten: Isolierung defekter Zeilen pro Zeile (nicht mehr die
ganze Liste betroffen), Tab "Alle" sortiert jetzt nach Vorgang, Korrektur-/
Duplikat-Zugehörigkeit über die Lead-Nummer sichtbar (Layout vorab mit
Marco abgestimmt) statt über Text-Badges, und die schon länger als
"später, nach Phase 4" vorgemerkten Spaltenfilter (Ort/Bundesland/Ampel/
Kanal/Status/Zugewiesen) sind jetzt gebaut.

**Block (e) ist gebaut** (`.github/workflows/retry-cron.yml`, Details in
der Checkliste unten) - laut Marcos Nachricht vom 17.08. der letzte
Schritt vor "Phase 4 durch". Er nannte Block (c) und (d) dabei nicht. Ob
das eine bewusste Scope-Entscheidung ist oder nur nicht erwähnt wurde, ist
mit ihm NICHT bestätigt - als offene Frage in den Block-(c)/(d)-Zeilen
unten vermerkt, nicht eigenmächtig übersprungen oder eigenmächtig doch
noch gebaut. **Nächster Schritt: mit Marco klären, ob (c)/(d) noch kommen
oder Phase 4 damit tatsächlich abgeschlossen ist.** Ampel-Funktion
existiert bereits (`app/core/ampel.py`, aus Phase 4 vorgezogen).
Auslandspfad + Landesbauordnung-Zuordnung kommen laut Marco separat NACH
Block (a)-(e).

**Mehrdeutig-Kriterium korrigiert (17.08., drei Funde, Details in
docs/FUNDE.md):** Die ursprüngliche Regel ("mehr als ein Nominatim-Treffer
= mehrdeutig") löste bei vollständigen Adressen fast durchgängig Gelb aus,
weil Nominatim für dieselbe Stelle oft mehrere OSM-Objekte liefert
(Gebäude, Ausstattung, Geschäfte) - Marco stoppte deshalb explizit vor
Block (b) und ließ das erst untersuchen. Neues Kriterium: Kandidaten
gelten als übereinstimmend, wenn Bundesland UND Gemeinde identisch sind -
dann `status=ok`, der Kandidat mit höchstem `importance`-Wert gewinnt,
protokolliert in `geocode_raw.auswahl` (Kandidatenzahl + Einstufung, damit
später nachvollziehbar bleibt, ob ein Treffer wirklich eindeutig war oder
unter mehreren ausgewählt wurde). Der Testfall "Lindenweg 3, Neustadt"
(Aufgabe, keine PLZ) bleibt mehrdeutig (3 echte Bundesländer). Dabei
zusätzlich gefunden: Nominatim liefert für Berlin und Hamburg (nicht
durchgängig für Bremen) kein `state`-Feld, nur den ISO-3166-2-Code - über
eine Lookup-Tabelle behoben, plus neues Feld `geo_state_unresolved`, das
ein unauflösbares Bundesland sichtbar statt still `None` macht. Beim
Live-Verifizieren der Fixes zusätzlich gefunden: `SERVICE_AREA_STATES=alle`
in `.env` (aus der Einrichtungsanleitung übernommen) wurde nicht erkannt
und ergab `in_service_area=False` für JEDE Adresse, also rote Ampel
"Außerhalb Deutschlands" für praktisch alles - behoben, "alle" wird jetzt
als Sentinel erkannt UND jeder Bundesland-Name gegen die echten 16 geprüft
(ein Tippfehler bricht die Anwendung jetzt beim Start ab, statt still
einen wirkungslosen Filter zu bilden). Zum Zeitpunkt dieses Funds waren
bestehende Leads noch nicht betroffen (alle 19 standen noch auf
`geocode_status='offen'`, Block (b) existierte noch nicht) - der bis dahin
aufgelaufene Bestand (u.a. aus `scripts/testlauf.py`) wurde erst bei der
Live-Verifikation von Block (b) tatsächlich geokodiert, s. dort. 33 Tests
in `tests/core/test_geocoding.py` (vorher 15), alle grün, zusätzlich live
gegen die echte API neu verifiziert (Berlin/Hamburg/Bremen einzeln
geprüft, nicht nur Berlin).

**Hinweis für Mail-Tests in dieser Session:** `usage_counters` (Tageslimit,
`MAX_EMAILS_PER_DAY=50`) steht nach dem intensiven Testen heute bei über 80
für den UTC-Tag - weitere Mail-Assertions in Tests können `mail_fehlgeschlagen`
("tageslimit_erreicht") statt `mail_gesendet` sehen. Kein Bug, s. Fund in
docs/TESTLAUF.md (F2-Fall) - Tests sollten auf "Mail-Versuch fand statt"
prüfen, nicht auf "Versand war erfolgreich".

**Neu gebaut seit Login:**
- `app/core/ampel.py` — Ampel-Funktion nach Konzept §B, aus Phase 4
  vorgezogen (reine Funktion, kein Geocoding nötig). `traffic_light`-Spalte
  bleibt unbeschrieben, die Liste/Detailansicht berechnen live; das Cachen
  bei jedem Schreibvorgang ist Teil von Phase 4.
- `app/core/display.py` — `format_berlin_datetime`, `STATUS_VALUE_LABELS`/
  `status_label()` (alle status-artigen Spalten), `EVENT_TYPE_LABELS`,
  `CONTACT_TIME_LABELS` (von `app/mail.py` hierher verschoben).
  `CHANNEL_LABELS` in `app/core/channel.py`, `SPAM_REASON_LABELS` in
  `app/core/spam.py`.
- `app/db.py::insert_event()` — war identisch dupliziert in
  `submission.py` und `mail.py`, mit `admin.py` als drittem Aufrufer
  konsolidiert.
- `GET /admin/leads/{lead_id}` — Detailansicht: alle Felder (auch leere),
  message prominent, superseded-Kette rückwärts aufgelöst + Banner bei
  duplicate_of/superseded_by, Event-Historie über die GANZE Kette.
- `POST /admin/leads/{lead_id}/bearbeitung` + `.../mail-erneut-senden` —
  Aktionen: Status/assigned_to/disqualify_reason, Mail-Resend. Details s.
  Phase-3-Checkliste unten.

**Beim Bauen gefunden und gefixt (gehört in `docs/FUNDE.md` beim Schreiben
der NOTES.md, Phase 6):**
1. `persist_submission()` setzte bei `is_spam=true` nie `status='spam'` -
   gefixt (Marcos Regel: Dedup-Folgen entfallen bei Spam komplett, kein
   Vorgänger wird berührt). Commit `7c7df2e`.
2. Beim Bauen der Aktionen fiel eine Folgeinkonsistenz aus der Zeit VOR
   Fix 1 auf: Alt-Leads mit `is_spam=true` bei `status='neu'` existieren in
   der DB. Der erste Entwurf der "Status ändern"-Aktion prüfte
   is_spam-Sync nur, wenn sich `status` gegenüber der DB änderte - bei so
   einem Alt-Lead ist die Freigabe (`status='neu'` erneut abschicken) aber
   keine Änderung, `is_spam` blieb fälschlich `true` stehen. Live-Test
   deckte es auf, Fix: is_spam/spam_reason/contacted_at richten sich jetzt
   nach dem eingereichten Status, unabhängig davon ob er sich geändert hat.

### Module (app/)
- `main.py` — Routen `/health`, `/` (Formular, inkl. Vorbefüllung über `?k=`),
  `/datenschutz`, `/danke`, `POST /submit` (Orchestrierung). `load_dotenv()`
  und `logging.basicConfig()` laufen ganz am Anfang, vor allen `app.*`-Imports
  (s. `docs/FUNDE.md` — sonst brechen Imports bzw. verschwinden Dry-Run-Logs).
- `admin.py` — `APIRouter(prefix="/admin")`: Login/Logout, Dashboard mit
  Lead-Liste (`GET /admin`). Session-Cookie über `app/core/admin_auth.py`
  (eigenes `SESSION_SECRET`). `_fetch_leads()` baut Tab-/Suche-/Sortier-Query
  (parametrisiert, LIMIT 500 s. Konzept §10), `_decorate_row()` ruft
  `app.core.ampel` + `format_berlin_datetime` pro Zeile auf und leitet die
  fünf Badges aus Konzept §6 her (2 per Subquery: erneut_angefragt/
  superseded_by-Rückverweis, 3 direkt aus Feldern der Zeile).
- `submission.py` — `persist_submission()`: Dedup-Kandidat suchen, Entscheidung
  aus `app.core.dedup` anwenden, INSERT/UPDATE + `lead_events` schreiben, alles
  auf einer Connection/Transaktion. `resolve_current_lead()` folgt der
  `superseded_by`-Kette für die Vorbefüllung.
- `mail.py` — `send_confirmation_email()`: Spam → keine Mail, sonst Tageslimit
  (`usage_counters`) prüfen, dann `DRY_RUN_EMAIL`-Zweig (volle Logik, kein
  Versand, Status `simuliert`) oder echter Brevo-Versand. Intro-Text variiert
  je nach `DedupCase` (`_INTRO_TEXT_BY_CASE`).
- `app/core/*` — reine Funktionen ohne DB/HTTP, je mit Tabellentest in
  `tests/core/`: `normalize.py`, `text.py`/`content_hash.py`, `dedup.py`,
  `merge.py`, `spam.py` (+ `SPAM_REASON_LABELS`), `validation.py`,
  `channel.py` (+ `CHANNEL_LABELS`), `edit_token.py`, `admin_auth.py`,
  `ampel.py` (Konzept §B, aus Phase 4 vorgezogen — reine Funktion, braucht
  kein echtes Geocoding), `display.py` (`format_berlin_datetime`, CLAUDE.md
  Regel 7).
- `db.py` — `get_connection()`, `prepare_threshold=None` für den Transaction
  Pooler, eine Connection pro Request.
- `config.py` — Kontingent-Env-Werte (`DRY_RUN_EMAIL`, `MAX_EMAILS_PER_DAY`, ...).
  Docstring dort ist veraltet ("wird von nichts importiert") — wird
  inzwischen von `app/mail.py` importiert, Kommentar bei Gelegenheit korrigieren.
- `templating.py` — gemeinsame `Jinja2Templates`-Instanz (verhindert Zirkelimport
  zwischen `main.py` und `admin.py`).

### Submit-Pfad (Kurzfassung)
`POST /submit` → `validate_submission` (422 bei Fehlern, Eingaben bleiben
erhalten) → `detect_spam` → Normalisierung (`normalize_phone/email/name`) →
`derive_channel` → `content_hash` → `persist_submission` (F1-F4-Entscheidung,
bei F3 `merge_fields`) → bei allem außer F1: `send_confirmation_email` (Fehler
dort brechen den Submit nie ab, CLAUDE.md Regel 2) → PRG-Redirect nach
`/danke?k=<edit_token>`.

### Dashboard — aktueller Stand
Vorhanden: Login (`GET/POST /admin/login`), Logout, Platzhalter-Dashboard
unter `GET /admin` ("Angemeldet als X"). Fehlt komplett: Lead-Liste, Tabs,
Detailansicht, Aktionen, CSV-Export, Auswertungs-Tab — siehe Phase 3 unten,
Punkte sind alle noch offen.

### Offene Punkte / Entscheidungen für die nächste Session
- **MX-Prüfung (Konzept §D):** bewusst NICHT eingebaut. `validate_submission`
  prüft nur Syntax (`email-validator`, `check_deliverability=False`), keine
  DNS-Abfrage. Begründung im Docstring von `app/core/validation.py`: ein
  Netzwerk-Aufruf während der reinen Validierung würde die Funktion nicht mehr
  ohne Netzwerk testbar machen. Muss vor Abgabe nochmal bewusst entschieden
  werden (einbauen vor `persist_submission` mit Timeout, oder als Scope-Cut in
  NOTES.md dokumentieren).
- **F2-Mailtext:** enthält aktuell einen Gedankenstrich ("... vorliegenden
  Anfrage — es hat sich nichts geändert."). In `app/mail.py`,
  `_INTRO_TEXT_BY_CASE[DedupCase.F2_DUPLIKAT]`. Vor Abgabe nochmal gegenlesen,
  ob das Zeichen so bleiben soll oder umformuliert wird (z.B. mit Punkt statt
  Gedankenstrich).
- **Retry-Endpunkt (`POST /admin/retry`) existiert noch nicht.** Fehlgeschlagene
  Mails (`email_status='fehlgeschlagen'`/`'offen'` nach Tageslimit) bleiben
  bis dahin unbehandelt liegen. Kommt mit Phase 4 (Geocoding), ist aber auch
  für Mail-Retries relevant — beim Bauen beide Fälle mitdenken.
- **Geocoding (Phase 4) noch nicht begonnen:** `DRY_RUN_GEOCODE`/
  `MAX_GEOCODE_PER_MINUTE` sind in `config.py` vorbereitet, aber nirgends
  benutzt.
- `.venv` ist die persistente Projekt-Umgebung (nicht neu anlegen). Aktuell
  108 pytest-Tests, alle grün (88 + 20 aus `test_ampel.py`/`test_display.py`).

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
- [x] E-Mail-Validierung: Client type=email + JS-Tippfehlervorschlag; Server Syntax (email-validator) — **MX-Prüfung bewusst ausgelassen, s. offene Punkte oben**
- [x] Namens-Normalisierung (nur bei durchgaengig GROSS/klein), name_raw erhalten, Tabellentest inkl. McDonald/van der Berg/Mueller-Luedenscheidt
- [x] Kanal-Ableitung beim INSERT: channel + channel_source nach Prioritaetsliste, Tabellentest
- [ ] process_after setzen (Env PROCESS_DELAY_MINUTES, Default 60) — noch nicht gebaut, hängt mit Phase 4 zusammen
- [x] Kontakthinweis im Formular-Footer und auf Fehlerseiten (Env-Variablen)
- [x] Bestätigungsmail: HTML-Template (Datenzusammenfassung, Korrektur-Hinweis, Erwartung, Kontaktblock), best effort, Statusfelder
- [x] Mail-Ausnahmen: nur F1 und Spam bekommen keine Mail (Konzept SS E)
- [x] Korrektur-Link mit Vorbefuellung: signiertes Token (itsdangerous, 7 Tage), GET /?k=... befuellt Formular, kein Schreibzugriff
- [x] Spam-Erkennung: Honeypot, Zeitschwelle, Link-Zaehler im message-Feld, Zeichensatz-Heuristik
- [x] pytest: normalize_phone (5 Beispielformate), content_hash-Stabilität, dedup_decision F1-F4, merge_fields (neu/leer/beide leer)

## Phase 3 — Dashboard (So, ~3-4h) ✅
- [x] Login (Env-Credentials, signierter Cookie, constant-time) — vom Nutzer live getestet, funktioniert
- [x] Tabs Neu/In Bearbeitung/Erledigt/Alle; duplicate/superseded/spam(+ausland, s.u.) default aus, Toggle "alles anzeigen"
- [x] Spalten inkl. Bundesland, Ampel Bearbeitbarkeit (grün/gelb/rot MIT Grundtext, Grund als eigene Spalte/unter Name auf schmal), Kanal (channel + heard_about getrennt) — Beschriftungen durchgängig deutsch, Volltextsuche über Name/E-Mail/Telefon/Ort, Leerzustand mit Meldung statt leerer Tabelle. Noch NICHT vom Nutzer im Browser getestet (nur curl gegen echte Daten).
- [x] Badges: erneut angefragt / Kontakt bekannt / Telefon prüfen / Adresse mehrdeutig, plus anklickbare Verweise ("Duplikat von Anfrage vom X" / "Ersetzt durch Anfrage vom X" / "Frühere Version vom X") zum jeweils verwandten Lead. duplikat/ersetzt/spam/ausland-Zeilen zusätzlich als ganze Zeile gedämpft (`row-inaktiv`), damit man die Dedup-Logik sieht statt sie zu erraten (Marco, 2026-08-16). Standardfilter (§6: diese vier nie im Neu/Bearbeitung/Erledigt-Tab, "Alle" ohne Toggle auch nicht) nochmal explizit über alle Tabs/Toggle-Kombinationen live verifiziert, kein Fund.
- [x] Detailansicht: alle Felder (auch leere), message prominent, superseded-Kette rückwärts aufgelöst + Banner bei duplicate_of/superseded_by, Event-Historie über die GANZE Kette (nicht nur den aktuellen Datensatz), Google-Maps-Link. Route `GET /admin/leads/{lead_id}`, verlinkt aus der Liste. Live gegen echte F3-Korrekturkette + Spam-Lead getestet, noch nicht im Browser vom Nutzer.
- [x] Aktionen: Status ändern (nur die 5 manuell sinnvollen Werte, s. `_MANUALLY_SETTABLE_STATUSES`), assigned_to, disqualify_reason als ein Formular (`POST /admin/leads/{id}/bearbeitung`), "Mail erneut senden" einzeln (`POST .../mail-erneut-senden`, ruft `send_confirmation_email` direkt). Status-Wechsel synct is_spam mit (Konzept §J: Fehlalarm manuell freigeben UND übersehenen Spam nachträglich markieren), setzt contacted_at automatisch beim ersten Wechsel auf 'kontaktiert', schreibt status_geaendert/zugewiesen-Events. Live getestet inkl. Selbstheilung eines inkonsistenten Alt-Leads (is_spam=true bei status='neu' aus der Zeit vor dem Spam-Fix) — **"Geocoding erneut"/globaler Retry-Button weiterhin nicht gebaut**, dafür gibt es vor Phase 4 nichts zum Retryen
- [x] CSV: `GET /admin/export.csv`, Semikolon, UTF-8 BOM (`utf-8-sig`), Europe/Berlin, deutsche Header, 27 Spalten (alle Eingabefelder + Kanal/Kanal-Quelle/Status/Ampel/Ampel-Grund + Qualitätsflags). Läuft über dieselben `_fetch_leads`/`_decorate_row` wie die Liste, damit Filter/Suche/Sortierung nie auseinanderlaufen können. Leere Felder als "" statt "–" (pivot-tauglich). Live getestet: BOM vorhanden, Filter/Suche respektiert (tab=neu → nur 2 Zeilen, Suche "Stuttgart" → nur Stuttgart-Zeilen), Sonderzeichen-Escaping mit echtem Semikolon+Zeilenumbruch+Anführungszeichen in einer Anmerkung geprüft (RFC4180 über csv-Modul, rundet exakt). **Noch nicht in Excel geöffnet** - das macht Marco selbst, deshalb hier angehalten.
- [x] Tab Auswertung (`GET /admin/auswertung`): GROUP BY **channel** (nicht utm_source, s. §H)/campaign/heard_about/Bundesland als Links statt Dropdown (kein JS), alle 8 Spalten aus §7, "Basis: n" pro Zeile, Quoten unter n=10 grau/kursiv, Kreuztabelle Kanal×Bundesland. Live gegen echte Daten verifiziert (Zahlen von Hand gegengerechnet, exakte Übereinstimmung). Fund beim Bauen behoben: `utm_campaign` wird beim Submit nicht leer→NULL normalisiert (anders als heard_about/phone/name) - ohne `NULLIF(...,'')` in der Query erschienen zwei optisch identische "(keine Angabe)"-Zeilen für NULL und ''. Query-seitig gefixt, Ursache in `main.py` (Submit-Handler) nicht angefasst - dort betrifft es auch utm_source/medium/term/content/gclid/fbclid/referrer/landing_page, nicht nur campaign.
- [x] **17.08. umgesetzt** (nach Block (b), wie damals vorgemerkt): die zwei Dropdown-Filter (Kanal, Bundesland) oben durch Filter an den Spaltenüberschriften Ort, Bundesland, Ampel, Kanal, Status und Zugewiesen ersetzt, jeweils aus `_distinct_values()` (echte DB-Werte, nicht mehr die feste Liste). Ampel als einzige Ausnahme mit fester kleiner Liste statt DISTINCT-Query - keine gespeicherte Spalte (`traffic_light` erst mit Block c), Filter greift deshalb erst nach dem Dekorieren in Python, nicht als SQL-WHERE; bei der aktuellen Datenmenge (< 50 Leads) unproblematisch, s. Kommentar in `app/admin.py`. Allgemeine Suche bleibt oben. Details s. neuer Punkt unter Block (b) unten.

## Phase 4 — Geocoding (Mo, ~2-3h) — Block (a)+(b)+(e) fertig, (c)/(d) offen (s. Stand oben)
- [x] **Block (a):** Nominatim-Client, zweigeteilt: `app/core/geocoding.py` (reine Auswertung einer bereits geparsten Antwort, testbar ohne Netzwerk, 33 Tests inkl. Nominatims uneinheitlicher Gemeinde-Schlüssel city/town/village/... und Pilot-Einzugsgebiet) + `app/geocoding.py` (echter Client: structured query street/city/postalcode getrennt, countrycodes=de, limit=5, format=jsonv2, addressdetails=1, User-Agent aus NOMINATIM_USER_AGENT-Env - fehlt der, wird gar nicht erst angefragt statt mit leerem Default, Timeout 3s). Status ok/mehrdeutig/nicht_gefunden (fehlgeschlagen kommt vom Client bei Netzwerk-/HTTP-Fehlern), volle Antwort + Auswahl-Protokoll für geocode_raw, Bundesland/Gemeinde/Koordinaten/in_service_area (+ geo_country als ISO-Code, nicht explizit gefordert aber dieselbe Antwort, günstig für die Ampel-Auslandsregel) abgeleitet. `in_service_area=None` (nicht `False`) wenn gar kein Bundesland ermittelbar war - "wissen wir nicht" ≠ "liegt draußen", dieselbe Unterscheidung wie in app/core/ampel.py. DRY_RUN_GEOCODE bewusst NICHT hier geprüft, sondern für Block (b) vorgesehen (wie MAX_GEOCODE_PER_MINUTE eine Frage des Retry-Laufs, nicht des Clients). **Mehrdeutig-Kriterium 17.08. korrigiert** (Bundesland+Gemeinde-Übereinstimmung statt roher Trefferzahl, `importance`-Tie-Breaker, Auswahl-Protokoll in `geocode_raw.auswahl`), dabei zwei weitere Live-Funde behoben (fehlendes `state`-Feld bei Berlin/Hamburg via ISO-3166-2-Fallback + neues `geo_state_unresolved`-Flag; `SERVICE_AREA_STATES=alle` wurde nicht erkannt und ergab `in_service_area=False` für alles - jetzt Sentinel-Erkennung plus Validierung beim Modul-Import). Alle drei Funde in docs/FUNDE.md. Live gegen die echte Nominatim-API neu verifiziert (Berlin/München jetzt korrekt "ok" statt "mehrdeutig", Lindenweg-3-Testfall weiterhin "mehrdeutig", Hamburg/Bremen einzeln auf das state-Feld geprüft).
- [x] **Block (b):** `POST /admin/retry` (`app/retry.py` + Route in `app/admin.py`), zwei Nachweise akzeptiert (Session-Cookie ODER `X-Retry-Secret`-Header, `verify_retry_secret` in `app/core/admin_auth.py`, `hmac.compare_digest`), Antwort JSON (Darstellung im Dashboard ist Block (d)s Entscheidung). Filtert immer auf `process_after <= now()` (CLAUDE.md), für Geocoding UND Mail auf `status IN ('offen','fehlgeschlagen')` - `mehrdeutig`/`nicht_gefunden` sind abgeschlossene Ergebnisse, kein Retry-Fall. Geocoding: `MAX_GEOCODE_PER_MINUTE` als Ratenbremse (usage_counters, counter_key `geocode_minute`) GETRENNT von `GEOCODE_BATCH_SIZE` (neues Env, Default 5) als Portionsgröße pro Aufruf - Marcos Vorgabe, "kurze wiederholbare Portionen statt eines Laufs, der gegen ein Zeitlimit drückt", 1.1s Pause zwischen Nominatim-Anfragen. Antwort meldet `verarbeitet` UND `verbleibend` (Backlog-Größe) getrennt für Geocoding/Mail - ausdrücklich verlangt, sonst nicht erkennbar ob eine Portion reichte. DRY_RUN_GEOCODE spiegelt DRY_RUN_EMAIL exakt (Kontingent-Zähler/Versuche/Event laufen voll durch, nur der echte Aufruf entfällt) → neuer `geocode_status='simuliert'` (Migration 0007, analog 0002). Neues Feld `geo_state_unresolved` (Migration 0008) wird jetzt tatsächlich persistiert. F3-Korrektur: `_supersede()` in `app/submission.py` setzt Vorgänger auf `geocode_status='entfaellt'` NUR wenn dessen Geocoding noch offen/fehlgeschlagen war (§G-Grenzfall: ein bereits geokodierter Vorgänger bleibt stehen). `send_confirmation_email()` gibt jetzt den resultierenden Status zurück (für die Zusammenfassung, ohne erneute Abfrage); `_row_to_new_lead_data` von `app/admin.py` nach `app/submission.py::row_to_new_lead_data` verschoben (jetzt von admin.py UND retry.py genutzt). **Zusätzlich `PROCESS_DELAY_MINUTES` verdrahtet** (war dokumentiert, aber wirkungslos - Fund, s. docs/FUNDE.md; `_insert_lead` setzt `process_after` jetzt explizit aus dem Env-Wert statt dem SQL-Spaltendefault). Live verifiziert (lokaler Server, `PROCESS_DELAY_MINUTES=0`): Auth (401 ohne/mit falschem Secret), echtes Geocoding inkl. Portionsgrenze und Backlog-Anzeige (9 Kandidaten → 5+4 über zwei Aufrufe), Kontingent-Erschöpfung mitten in der Verarbeitung (Rest bleibt unangetastet liegen), DRY_RUN_GEOCODE inkl. Kontingent-Prüfung, F3 → Vorgänger `entfaellt` UND vom Retry ausgeschlossen, Mail-Retry-Erholung von `tageslimit_erreicht`. Keine automatisierten Tests für `app/retry.py` selbst (wie `app/mail.py`/`app/geocoding.py`/`app/admin.py` - CLAUDE.md Regel 5 gilt nur für app/core/*), aber `verify_retry_secret` (app/core/admin_auth.py) pur und getestet.
- [x] **17.08., zwischen Block (b) und (e):** Marco meldete einen 500er im Dashboard - `geocode_status='simuliert'` (neu seit Block b) fehlte in `app/core/ampel.py`, das bei jedem unbekannten Wert bewusst wirft (CLAUDE.md Regel 3). Der eigentliche Fund war nicht der fehlende Wert, sondern dass diese korrekte Absicherung ungeschützt in der Schleife über die ganze Lead-Liste saß - EIN betroffener Lead riss die GANZE Liste mit ab (s. docs/FUNDE.md). Vier Punkte umgesetzt: (1) Isolierung pro Zeile: `_decorate_row_safe()` fängt jeden Fehler einzeln ab, eine defekte Zeile erscheint mit eigenem Ampel-Status "defekt" (Rand/Musterung statt Farbe) und Text "Fehler bei der Anzeige" statt die Liste zu zerstören - live mit einer absichtlich kaputten Zeile verifiziert. (2) Tab "Alle" sortiert jetzt standardmäßig nach Vorgang (`lead_nummer DESC`, innerhalb derselben Nummer `created_at ASC`) statt neueste zuerst - Neu/Bearbeitung bleiben bei ältester zuerst (Warteschlange), Erledigt kann eine 'ersetzt'-Zeile per Tab-Filter ohnehin nie zeigen. (3) Zugehörigkeit jetzt über die Lead-Nummer sichtbar statt über die Badges "Teil einer Korrekturkette/Duplikatgruppe" (ersatzlos gestrichen, samt `_kette_info`/`_duplikatgruppe_info`): zusammengehörige Zeilen teilen sich einen getönten Hintergrund als EIN Block ohne Trennstrich dazwischen (Layout-Vorschlag mit Marco abgestimmt, Screenshots/ASCII-Mockup vorab gezeigt), Status zeigt "{Status}, Version {Position} von {Gesamt}" (z.B. "Ersetzt, Version 1 von 2") - Position/Gesamt über `_fetch_vorgang_positions()` per Fenster-Funktion, ausdrücklich über ALLE Zeilen mit dieser Nummer (nicht nur die im aktuellen Tab sichtbaren), sonst hätte ein gefilterter Tab eine falsch kleine Gruppengröße gezeigt. Live mit den drei realen Fällen aus Marcos Meldung verifiziert (Thomas Ahrens #12, Kai Ruthenberg #14, Jörg Klöpper #15 - alle drei jetzt direkt benachbart mit korrekter Versionsangabe). (4) Spaltenfilter wie oben unter Phase 3 vermerkt.
- [ ] **Block (c):** traffic_light/traffic_light_reason beim Schreiben berechnen und speichern statt live beim Lesen (app/core/ampel.py bleibt die reine Funktion, nur der Aufrufer ändert sich) - **laut Marcos Nachricht vom 17.08. nicht mehr Teil der Reihenfolge vor "Phase 4 durch"** (er nannte nur Spaltenfilter + Block (e) als verbleibend) - noch nicht mit ihm bestätigt, ob das Absicht ist; hier nur der Stand vermerkt, nicht eigenmächtig gebaut.
- [ ] **Block (d):** Dashboard mit echten Ampel-Werten (schon länger live), Bundesland gefüllt (schon länger live), Kandidaten bei mehrdeutig in der Detailansicht, Google-Maps-Link aus lat/lon (existiert schon, s. `_field_groups`), Buttons "Geocoding erneut" (einzeln) + globaler Retry - **dieselbe Unklarheit wie bei Block (c)**, s. Zeile oben.
- [x] **Block (e):** `.github/workflows/retry-cron.yml`, `schedule: */15 * * * *` (Standard-Cron-Syntax für "alle 15 Minuten") + `workflow_dispatch` (manueller Anstoß im GitHub-UI zum Testen ohne zu warten). `curl -sS --fail` gegen `${{ vars.RETRY_URL }}/admin/retry` mit Header `X-Retry-Secret: ${{ secrets.RETRY_SECRET }}` - `--fail` lässt den Job sichtbar rot werden statt eine tote Verbindung/falsches Secret stillschweigend zu ignorieren. Braucht zwei Werte in den Repo-Einstellungen (Settings > Secrets and variables > Actions), die NICHT von hier aus gesetzt werden können: Variable `RETRY_URL` (Basis-URL des Vercel-Deployments) und Secret `RETRY_SECRET` (identisch mit `.env`). **Ehrlich zum Stand:** YAML-Syntax lokal geprüft (`yaml.safe_load`), aber NICHT gegen ein echtes Deployment live verifiziert - dafür fehlen die tatsächliche Vercel-URL und die Möglichkeit, GitHub Actions von hier aus auszulösen. Marco sollte nach dem nächsten Deploy einmal manuell über "Run workflow" (workflow_dispatch) im GitHub-UI testen.
- [ ] Auslandspfad (status=ausland, zweite Mail, expansion_opt_in) und Bundesland→Landesbauordnung-Mapping: laut Marco separat NACH (a)-(e), nicht Teil dieser Reihenfolge

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
