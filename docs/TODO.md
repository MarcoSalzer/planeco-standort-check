# Standort-Check: To-do (v2)

Abgabe: Do 20.08. 10:00 an Tessa, CC Björn + Basti. Interview: Fr 21.08. 10:00.
Fenster: Fr 14.08. mittags bis Mi 19.08. abends. Mi ist Puffer.

## Stand 16.08. abends (4) — für den Einstieg in eine neue Session

Phase 1 und Phase 2 sind fertig und committet (15 Commits, siehe `git log`).
Phase 3: Login, Lead-Liste (inkl. sichtbarer Dedup-Beziehungen), Detail-
ansicht, Aktionen UND CSV-Export sind fertig (s. Checkliste unten).
**Nächster Schritt: Auswertungs-Tab** — schließt Phase 3 ab, danach Phase 4
(Geocoding). Marco hält bewusst nach dem CSV an, um die Datei einmal
selbst in Excel zu öffnen - noch nichts aus Phase 3 wurde im Browser
gegengetestet, alles nur live per curl/httpx gegen echte Supabase-Daten
verifiziert (inkl. echter F3-Korrekturketten, Spam-Fällen und jetzt einer
Anmerkung mit Semikolon+Zeilenumbruch+Anführungszeichen fürs CSV-Escaping).

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

## Phase 3 — Dashboard (So, ~3-4h) — Login + Lead-Liste fertig, Rest offen
- [x] Login (Env-Credentials, signierter Cookie, constant-time) — vom Nutzer live getestet, funktioniert
- [x] Tabs Neu/In Bearbeitung/Erledigt/Alle; duplicate/superseded/spam(+ausland, s.u.) default aus, Toggle "alles anzeigen"
- [x] Spalten inkl. Bundesland, Ampel Bearbeitbarkeit (grün/gelb/rot MIT Grundtext, Grund als eigene Spalte/unter Name auf schmal), Kanal (channel + heard_about getrennt) — Beschriftungen durchgängig deutsch, Volltextsuche über Name/E-Mail/Telefon/Ort, Leerzustand mit Meldung statt leerer Tabelle. Noch NICHT vom Nutzer im Browser getestet (nur curl gegen echte Daten).
- [x] Badges: erneut angefragt / Kontakt bekannt / Telefon prüfen / Adresse mehrdeutig, plus anklickbare Verweise ("Duplikat von Anfrage vom X" / "Ersetzt durch Anfrage vom X" / "Frühere Version vom X") zum jeweils verwandten Lead. duplikat/ersetzt/spam/ausland-Zeilen zusätzlich als ganze Zeile gedämpft (`row-inaktiv`), damit man die Dedup-Logik sieht statt sie zu erraten (Marco, 2026-08-16). Standardfilter (§6: diese vier nie im Neu/Bearbeitung/Erledigt-Tab, "Alle" ohne Toggle auch nicht) nochmal explizit über alle Tabs/Toggle-Kombinationen live verifiziert, kein Fund.
- [x] Detailansicht: alle Felder (auch leere), message prominent, superseded-Kette rückwärts aufgelöst + Banner bei duplicate_of/superseded_by, Event-Historie über die GANZE Kette (nicht nur den aktuellen Datensatz), Google-Maps-Link. Route `GET /admin/leads/{lead_id}`, verlinkt aus der Liste. Live gegen echte F3-Korrekturkette + Spam-Lead getestet, noch nicht im Browser vom Nutzer.
- [x] Aktionen: Status ändern (nur die 5 manuell sinnvollen Werte, s. `_MANUALLY_SETTABLE_STATUSES`), assigned_to, disqualify_reason als ein Formular (`POST /admin/leads/{id}/bearbeitung`), "Mail erneut senden" einzeln (`POST .../mail-erneut-senden`, ruft `send_confirmation_email` direkt). Status-Wechsel synct is_spam mit (Konzept §J: Fehlalarm manuell freigeben UND übersehenen Spam nachträglich markieren), setzt contacted_at automatisch beim ersten Wechsel auf 'kontaktiert', schreibt status_geaendert/zugewiesen-Events. Live getestet inkl. Selbstheilung eines inkonsistenten Alt-Leads (is_spam=true bei status='neu' aus der Zeit vor dem Spam-Fix) — **"Geocoding erneut"/globaler Retry-Button weiterhin nicht gebaut**, dafür gibt es vor Phase 4 nichts zum Retryen
- [x] CSV: `GET /admin/export.csv`, Semikolon, UTF-8 BOM (`utf-8-sig`), Europe/Berlin, deutsche Header, 27 Spalten (alle Eingabefelder + Kanal/Kanal-Quelle/Status/Ampel/Ampel-Grund + Qualitätsflags). Läuft über dieselben `_fetch_leads`/`_decorate_row` wie die Liste, damit Filter/Suche/Sortierung nie auseinanderlaufen können. Leere Felder als "" statt "–" (pivot-tauglich). Live getestet: BOM vorhanden, Filter/Suche respektiert (tab=neu → nur 2 Zeilen, Suche "Stuttgart" → nur Stuttgart-Zeilen), Sonderzeichen-Escaping mit echtem Semikolon+Zeilenumbruch+Anführungszeichen in einer Anmerkung geprüft (RFC4180 über csv-Modul, rundet exakt). **Noch nicht in Excel geöffnet** - das macht Marco selbst, deshalb hier angehalten.
- [ ] Tab Auswertung: GROUP BY utm_source/campaign/heard_about/Bundesland, Quoten + Qualitätsanteile, n<10 ausgegraut, Kreuztabelle Kanal x Bundesland

## Phase 4 — Geocoding (Mo, ~2-3h)
- [ ] Nominatim: structured query, countrycodes=de, limit=5, User-Agent, Timeout
- [ ] ok/mehrdeutig/nicht_gefunden/fehlgeschlagen, geocode_raw, in_service_area (Default alle 16, Env)
- [ ] Ampel-Funktion nach Konzept §B (10 Regeln, Prioritätsreihenfolge, Grundtext) + Tabellentest
- [ ] Auslandspfad: status=ausland, zweite Mail via Retry, expansion_opt_in
- [ ] Bundesland → Landesbauordnung Mapping (16 Einträge, statisch) in Detailansicht
- [ ] Ambiguitäts-Anzeige mit Kandidaten
- [ ] GitHub-Actions-Cron 15 min -> /admin/retry (Secret-Header); Dedup-Nachlauf 24h
- [ ] Retry verarbeitet nur process_after <= now(); bei F3 Vorgaenger auf geocode_status=entfaellt setzen

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
