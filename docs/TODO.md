# Standort-Check: To-do (v2)

Abgabe: Do 20.08. 10:00 an Tessa, CC Björn + Basti. Interview: Fr 21.08. 10:00.
Fenster: Fr 14.08. mittags bis Mi 19.08. abends. Mi ist Puffer.

## Phase 0 — Konzept fixieren (Chat) ✅ weitgehend
- [x] Datenmodell + Pipeline + Risiken (KONZEPT v2)
- [x] Review-Runde: Felder, Duplikat-Semantik, Mail-Regel, Konflikte K1-K6
- [x] Review 2: Pflichtfelder, Ampel, Feld-Merge, Auswertungs-Tab, deutsche Statuswerte
- [x] Review 3: Auslandspfad, Ampelregeln, Bundesland-Mapping, E-Mail-Prüfung, Mail-Ausnahmen
- [x] Review 4: Korrekturfenster 1h, Kanal-Ableitung, Namens-Normalisierung, Spam-Muster, Kontakt im Footer
- [ ] Nur noch offen: nichts. Konzept ist final.

## Phase 1 — Accounts & Skelett (Fr, ~2-3h)
- [ ] Accounts nach SETUP.md Schritt 1: Brevo zuerst (Verifizierung!), dann Supabase, Vercel, GitHub
- [ ] Lokaler Ordner + git init + docs/ (SETUP.md Schritt 2), CLAUDE.md ins Wurzelverzeichnis
- [ ] Repo `planeco-standort-check` (public), .env.example, attribution-Setting
- [ ] FastAPI-Skelett deployed auf Vercel, URL erreichbar
- [ ] Schema v2 in Supabase (leads + lead_events), Testzeile schreiben/lesen
- [ ] Env-Variablen bei Vercel
- **Abbruchkriterium:** läuft das Fr abend nicht → Sa früh Ursache klären, nicht auf wackligem Deploy weiterbauen

## Phase 2 — Kernpfad (Sa, ~4-5h)
- [ ] Formular mit Feldliste §3.1 v3 (nur Adresse+E-Mail+Datenschutz Pflicht, Rest optional markiert)
- [ ] Hidden Fields: utm_*, gclid, fbclid, referrer, landing_page, token, rendered_at, Honeypot
- [ ] POST /submit: Server-Validierung (422 re-rendert MIT Eingaben), Normalisierung, content_hash, Dedup-Entscheidung F1-F4, INSERT, PRG
- [ ] F3 Feld-Merge (neu gewinnt bei Konflikt, alt füllt Lücken) + superseded-Kette + Events mit changed_fields/merged_fields
- [ ] E-Mail-Validierung: Client type=email + JS-Tippfehlervorschlag; Server Syntax + MX (email-validator)
- [ ] Namens-Normalisierung (nur bei durchgaengig GROSS/klein), name_raw erhalten, Tabellentest inkl. McDonald/van der Berg/Mueller-Luedenscheidt
- [ ] Kanal-Ableitung beim INSERT: channel + channel_source nach Prioritaetsliste, Tabellentest
- [ ] process_after setzen (Env PROCESS_DELAY_MINUTES, Default 60)
- [ ] Kontakthinweis im Formular-Footer und auf Fehlerseiten (Env-Variablen)
- [ ] Bestätigungsmail: HTML-Template (Datenzusammenfassung, Korrektur-Hinweis, Erwartung, Kontaktblock), best effort, Statusfelder
- [ ] Mail-Ausnahmen: nur F1 und Spam bekommen keine Mail (Konzept SS E)
- [ ] Korrektur-Link mit Vorbefuellung: signiertes Token (itsdangerous, 7 Tage), GET /?k=... befuellt Formular, kein Schreibzugriff
- [ ] Spam-Erkennung: Honeypot, Zeitschwelle, Link-Zaehler im message-Feld, Zeichensatz-Heuristik
- [ ] pytest: normalize_phone (5 Beispielformate), content_hash-Stabilität, dedup_decision F1-F4, merge_fields (neu/leer/beide leer)

## Phase 3 — Dashboard (So, ~3-4h)
- [ ] Login (Env-Credentials, signierter Cookie, constant-time)
- [ ] Tabs Neu/In Bearbeitung/Erledigt/Alle; duplicate/superseded/spam default aus, Toggle
- [ ] Spalten inkl. Bundesland, Ampel Bearbeitbarkeit (grün/gelb/rot MIT Grundtext), Kanal (utm_source + heard_about getrennt)
- [ ] Badges: erneut angefragt / vom Kunden aktualisiert / Kontakt bekannt / Telefon prüfen / Adresse mehrdeutig
- [ ] Detailansicht: message prominent, superseded-Kette ausgegraut, Event-Historie, Google-Maps-Link
- [ ] Aktionen: Status, assigned_to, disqualify_reason, Mail/Geocoding-Retry einzeln, globaler Retry
- [ ] CSV: Semikolon, UTF-8 BOM, Europe/Berlin, Qualitätsspalten
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
