# Standort-Check: Datenmodell & Pipeline-Konzept (v3)

Arbeitsdokument. v3 nach zweiter Review-Runde mit Marco: Pflichtfeld-Logik minimiert,
Ampel auf Bearbeitbarkeit umgestellt, Feld-Merge bei Korrektur, Auswertungs-Tab,
deutsche Statuswerte, Attributionslogik korrigiert.

v2 war die erste Review-Runde mit Marco: neue Formularfelder, überarbeitete
Duplikat-Semantik (Korrektur via erneutem Absenden), Mail bei jedem Submit,
Datenqualität pro Kanal, Einzugsgebiet-Recherche. Änderungen ggü. v1: **[v2]**.

---

## 0. Einzugsgebiet & Ampel-Logik [v3 überarbeitet]

**Recherche:** planecobuilding.de wirbt durchgängig mit "bundesweit / deutschlandweit,
alle 16 Bundesländer" (>1.400 Bauanträge). Das Einzugsgebiet ist also ganz Deutschland.

**Konsequenz:** Eine Ampel "innerhalb/außerhalb Bundesland" wäre bei bundesweitem
Angebot fast immer grün und damit nutzlos. Die Ampel wird deshalb auf das gekoppelt,
was das Sales-Team morgens wirklich wissen muss: **Ist dieser Lead sofort bearbeitbar?**

| Ampel | Bedeutung | Bedingung |
|---|---|---|
| 🟢 **Bearbeitbar** | Kontaktweg da, Adresse eindeutig in DE verortet | geocode_status='ok' AND in_service_area=true AND phone_valid=true |
| 🟡 **Prüfen** | Bearbeitbar, aber etwas ist unsicher | geocode_status='ambiguous' OR postal_code IS NULL OR phone_valid=false |
| 🔴 **Problem** | Nicht ohne Klärung bearbeitbar | geocode_status IN ('not_found','failed') OR in_service_area=false (Ausland) |

Tooltip/Spalte nennt immer den konkreten Grund ("Adresse mehrdeutig: 3 Kandidaten",
"Telefonnummer nicht lesbar", "Adresse nicht auffindbar"). Nie nur eine Farbe ohne Text.

`SERVICE_AREA_STATES` bleibt als Env-Variable bestehen (Default: alle 16 Bundesländer),
damit ein Pilot-Rollout auf einzelne Regionen ohne Code-Änderung möglich wäre.
In den Notizen als Annahme kennzeichnen.

## 1. Datenfluss (Pipeline)

```
Anzeige (Meta/Google) → Link MIT utm_*/gclid/fbclid → Landingpage/Formular
        │
        ▼
[Formular /]   sichtbare Felder s. §3.1
        │      Hidden: utm_source/medium/campaign/term/content, gclid, fbclid,
        │      referrer, landing_page, submission_token, form_rendered_at, Honeypot
        ▼
[POST /submit]
  1. Serverseitige Pflichtfeld-Validierung
     → fehlt Pflichtfeld: 422, Formular re-rendert MIT erhaltenen Eingaben
       und Fehlermarkierung. NICHT speichern-und-verwerfen.            [v2]
  2. Honeypot / Zeitschwelle → is_spam=true (speichern, keine Mail)
  3. Normalisierung: Telefon→E.164, E-Mail→lower/trim, Adresse→trim/collapse
  4. content_hash über normalisierte Inhaltsfelder                      [v2]
  5. Duplikat-Entscheidung (§4) → Kennzeichnung / Vererbung
  6. INSERT (submission_token unique → Doppelklick idempotent)
  7. Best effort ≤3s, Fehler brechen NIE den Submit:
     a) Bestätigungsmail (Brevo) — bei JEDEM neuen Submit-Vorgang       [v2]
     b) Geocoding (Nominatim)
  8. Redirect Danke-Seite (Post/Redirect/Get)
        │
        ▼
[/admin/retry]  arbeitet email_status/geocode_status ∈ {pending,failed} ab
                + Dedup-Nachlauf 24h (Race-Absicherung)
                Trigger: Dashboard-Button + GitHub-Actions-Cron 15 min
                (hält zugleich Supabase Free Tier aktiv)
        │
        ▼
[Dashboard /admin]  Login → Tabs, Gruppierung, Statuspflege, CSV, Maps-Link
```

Kernmuster unverändert: Nebenwirkungen = Status + Zähler + letzter Fehler + ein
gemeinsamer Retry-Pfad (Vercel Serverless hat keine verlässlichen Background-Tasks).

## 2. Schema

### `leads`

```sql
create table leads (
  id                  uuid primary key default gen_random_uuid(),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  submission_token    uuid not null unique,

  -- Kontakt (Pflicht; raw bleibt unangetastet)
  name                text,                          -- optional (s. 3.1)
  email               text not null,                 -- Pflicht (Bestätigungsmail)
  email_normalized    text not null,
  phone_raw           text,                          -- optional
  phone_e164          text,
  phone_valid         boolean not null default false,

  -- Grundstücksadresse (die EINZIGE Adresse im System, s. K1)
  street              text not null,
  postal_code         text,
  city                text not null,

  -- Neue fachliche Felder [v2]
  is_owner            boolean,                       -- Eigentümer? ja/nein/k.A.
  contact_time_preference text
                      check (contact_time_preference in
                             ('vormittags','nachmittags','abends','flexibel')
                             -- 'abends' bei Implementierung ergänzt, 2026-08-16,
                             -- Migration 0004_contact_time_abends.sql
                             or contact_time_preference is null),
  message             text,                          -- Anmerkungen/Fragen
  heard_about         text,                          -- Selbstauskunft-Kanal
                      -- (google, meta, empfehlung, sonstiges)

  -- Attribution (automatisch, primäre Quelle)
  utm_source          text, utm_medium text, utm_campaign text,
  utm_term            text, utm_content text,
  gclid               text, fbclid text,
  referrer            text, landing_page text,

  -- Dedup / Versionierung [v2]
  content_hash        text not null,                 -- Hash normalisierter Inhalte
  duplicate_of        uuid references leads(id),     -- identische Wiederholung
  superseded_by       uuid references leads(id),     -- durch Korrektur ersetzt

  -- Sales-Workflow
  status              text not null default 'neu'
                      check (status in ('neu','kontaktiert','qualifiziert',
                                        'disqualifiziert','duplikat','ersetzt','spam')),
  assigned_to         text,
  contacted_at        timestamptz,
  disqualify_reason   text,

  -- Spam
  is_spam             boolean not null default false,
  spam_reason         text,

  -- Nebenwirkung Mail
  email_status        text not null default 'offen'
                      check (email_status in ('offen','gesendet','fehlgeschlagen')),
  email_attempts      int not null default 0,
  email_last_error    text,
  email_sent_at       timestamptz,

  -- Nebenwirkung Geocoding
  geocode_status      text not null default 'offen'
                      check (geocode_status in ('offen','ok','mehrdeutig',
                                                'nicht_gefunden','fehlgeschlagen')),
  geocode_attempts    int not null default 0,
  lat numeric, lon numeric,
  geo_municipality    text,
  geo_state           text,
  geocode_raw         jsonb,
  in_service_area     boolean,

  privacy_accepted_at timestamptz not null
);

create index on leads (created_at desc);
create index on leads (status);
create index on leads (email_normalized);
create index on leads (phone_e164);
create index on leads (content_hash);
```

`email_status='uebersprungen'` [umbenannt von `'skipped'` bei Implementierung,
2026-08-16, Migration `0003_email_status_uebersprungen.sql` — `'skipped'` war ein
Übernahme-Fehler aus dem englischen Wortlaut hier im Fließtext, K8 verlangt
deutsche Statuswerte]: für Spam-Fälle, bei denen bewusst kein Versandversuch
unternommen wird (§E). Für duplicate-Einträge nicht relevant — aktuell wird
immer gesendet (§4).

`email_status='simuliert'` [bei Implementierung ergänzt, 2026-08-15, Migration
`0002_email_status_simuliert.sql`]: für `DRY_RUN_EMAIL=true`. Läuft die komplette
Mail-Logik (Statusfelder, Events, Tageslimit-Zähler) durch, nur der echte
Brevo-Aufruf unterbleibt — ohne eigenen Wert wäre ein Dry-Run von einem echten
Versand (`gesendet`) nicht unterscheidbar.

### `lead_events` (append-only)

```sql
create table lead_events (
  id          bigint generated always as identity primary key,
  lead_id     uuid not null references leads(id),
  event_type  text not null,
  payload     jsonb,
  created_at  timestamptz not null default now()
);
```

Event-Typen (deutsch, s. K8): `erstellt`, `status_geaendert`, `zugewiesen`,
`mail_gesendet`, `mail_fehlgeschlagen`, `geocodiert`, `erneut_angefragt`, `ersetzt`,
`kontakt_bekannt` [bei Implementierung ergänzt, 2026-08-15].

`kontakt_bekannt`: F4 (Konzept §4) - gleiche Person, anderes Grundstück - hat in
§2 keine eigene Speicherung; `duplicate_of`/`superseded_by` decken nur F2/F3 ab.
Statt einer neuen Spalte trägt der neue Lead ein Event `kontakt_bekannt` mit
`{"bekannter_lead_id": "..."}` im Payload - reicht fürs Dashboard-Badge "Kontakt
bekannt" (§6), ohne das bereits eingespielte Schema zu ändern.

**Was das konkret ist — Beispiel.** Ein Lead kommt Montag rein, wird Dienstag von
Anna angerufen, Mittwoch schickt der Kunde eine korrigierte Telefonnummer.
`leads` enthält danach **eine** Zeile mit dem aktuellen Stand. `lead_events` enthält:

| lead_id | event_type | payload | created_at |
|---|---|---|---|
| a1… | erstellt | {"quelle":"formular"} | Mo 09:12 |
| a1… | mail_gesendet | {"an":"t.ahrens@…"} | Mo 09:12 |
| a1… | geocodiert | {"status":"ok","ort":"Dresden"} | Mo 09:13 |
| a1… | zugewiesen | {"an":"anna"} | Di 08:30 |
| a1… | status_geaendert | {"von":"neu","nach":"kontaktiert"} | Di 10:05 |
| a1… | ersetzt | {"changed":{"phone":["0170…","0171…"]}} | Mi 14:20 |

"Jetzt bauen statt später nachrüsten" heißt schlicht: **diese Zeilen entstehen nur,
wenn der Code sie im Moment der Änderung schreibt.** Baust du die Tabelle erst nächste
Woche, existieren die Ereignisse von Montag bis Mittwoch nirgends mehr — `leads` hat
nur den Endzustand, nicht den Weg dahin. Vergangenheit lässt sich nicht rekonstruieren.
Aufwand: eine INSERT-Zeile an jeder Stelle, die ohnehin geschrieben wird. Nutzen:
"Ø Zeit bis Erstkontakt" im Auswertungs-Tab und die vollständige Korrekturhistorie.

## 3. Formular

### 3.1 Felder [v3 — Pflichtlogik überarbeitet]

Leitsatz: **Der Standort-Check ist ein Lead-Magnet, kein Antrag.** Die eigentliche
Prüfung passiert im Sales-Gespräch (Aufgabe: "wird anschließend von unserem
Sales-Team kontaktiert"). Datenvollständigkeit ist deshalb ein Ziel für den Zeitpunkt
*nach* dem Erstkontakt, nicht für das Formular. Minimale Hürde schlägt Vollständigkeit.

| Feld | Typ | Pflicht | Spalte |
|---|---|---|---|
| Straße + Hausnr. (Grundstück) | text | **ja** | street |
| Ort (Grundstück) | text | **ja** | city |
| PLZ (Grundstück) | text, 5-stellig wenn gefüllt | nein | postal_code |
| E-Mail | email | **ja** | email |
| Telefon | tel | nein | phone_raw |
| Name | text | nein | name |
| Eigentümer des Grundstücks? | Radio ja/nein | nein | is_owner |
| Wann erreichen wir Sie am besten? | Select vormittags/nachmittags/abends/flexibel | nein | contact_time_preference |
| Wie sind Sie auf uns aufmerksam geworden? | Select | nein | heard_about |
| Anmerkungen oder Fragen | textarea | nein | message |
| Datenschutz-Checkbox | checkbox | **ja** | privacy_accepted_at |

**Nur drei Pflichtfelder** (Adresse zweiteilig, E-Mail, Datenschutz). Begründung je Feld:

- **Grundstücksadresse Pflicht:** Ohne Standort gibt es keinen Standort-Check. Das ist
  das Produkt, nicht ein Datenwunsch.
- **E-Mail Pflicht:** Pflichtteil 3 der Aufgabe verlangt eine automatische
  Bestätigungsmail. Ohne E-Mail-Adresse kann diese Pflichtfunktion nicht auslösen.
  Ein System, in dem eine geforderte Funktion für einen Teil der Fälle still
  ausbleibt, ist genau der Fehlertyp, den die Aufgabe testet (§K7 für die
  verworfene Entweder-oder-Variante).
- **Telefon optional:** Genau das Feld, an dem datenschutzsensible Interessenten
  abspringen (Angst vor Kaltakquise). Der Kontaktweg ist über E-Mail gesichert.
  Hinweistext: "Für eine schnellere Rückmeldung — optional."
- **Name optional:** Fragt das Sales-Team im Gespräch ab. Bestätigungsmail startet
  dann mit neutraler Anrede.

Adressblock klar überschrieben ("Adresse des Grundstücks"), autocomplete-Attribute
für Mobil, optionale Felder sichtbar als "(optional)" markiert.

### 3.2 Attribution: was automatisch kommt und was nicht [v3 korrigiert]

**Faktenlage (v2 war hier ungenau):**

- **Automatisch, ohne Zutun:** Google Ads hängt bei aktiviertem Auto-Tagging `gclid`
  an jeden Anzeigen-Klick, Meta hängt `fbclid` an. Beides ist Standardverhalten.
  Damit ist die Unterscheidung Google vs. Meta praktisch immer gesichert.
- **Nicht automatisch:** `utm_source/medium/campaign/term/content` müssen im
  Kampagnen-Setup manuell in der Ziel-URL hinterlegt werden. Übliche Praxis, aber
  keine Garantie — ob Planeco das durchgängig tut, weiß ich nicht.
- **Gar nicht abgedeckt:** Empfehlung durch Bekannte, organische Suche, Direkteingabe,
  Offline-Kontakt, Flyer. Diese Kanäle erzeugen keine Parameter.

**Deshalb ist `heard_about` (Selbstauskunft) kein Ersatz und keine Dopplung, sondern
die Abdeckung der dritten Gruppe.** Beide Quellen bleiben getrennte Spalten und
werden nie zusammengerechnet.

**Zu den Beispielanfragen:** Die Tabelle in der Aufgabe zeigt keine Lead-Herkunft.
Das ist kein Hinweis darauf, dass Herkunft nicht erfasst werden soll — die Tabelle
listet, was ein *Nutzer eintippt*, nicht was das *System aus der URL liest*.
Pflichtteil 6 verlangt Auswertbarkeit nach Kampagne und Kanal ausdrücklich; die
Herkunft muss also erfasst werden, nur eben unsichtbar aus der URL.

Optionen `heard_about`: Google-Suche / Google-Anzeige / Facebook oder Instagram /
Empfehlung / Sonstiges. (Trennung Suche vs. Anzeige, weil sie in der Auswertung
gegen gclid geprüft werden kann.)

## 4. Duplikat- & Korrektur-Semantik [v3]

Statuswerte auf Deutsch (s. K8). Vier Fälle:

| Fall | Auslöser (konkret) | Verhalten | Mail? |
|---|---|---|---|
| **F1** Technische Dopplung | Nutzer klickt "Absenden" zweimal in Folge, oder drückt auf der Ergebnisseite F5/Reload → Browser schickt **dasselbe Formular ein zweites Mal**. Erkennbar am identischen `submission_token`. | Zweiter Request erzeugt keinen neuen Datensatz (unique constraint), Nutzer sieht dieselbe Danke-Seite. | **nein** — es war ein Absendevorgang, die Mail lief bereits |
| **F2** Erneute Anfrage, identischer Inhalt | Nutzer ruft das Formular neu auf und füllt es identisch aus (neuer Token, gleicher `content_hash`). | Neuer Datensatz `status='duplikat'`, `duplicate_of` → Original. Original bekommt Event `erneut_angefragt` + Dashboard-Badge. | **ja** |
| **F3** Korrektur / Ergänzung | Neuer Token, Person **oder** Grundstück matchen, Inhalt weicht ab (auch: mehr oder weniger Felder ausgefüllt). | **Feld-Merge, s. u.** Neuer Datensatz wird führend und erbt Bearbeitungsstand; Vorgänger `status='ersetzt'`, `superseded_by` → neu, bleibt vollständig erhalten (ausgegraut). Event `ersetzt` mit Feld-Diff alt→neu. | **ja** |
| **F4** Gleiche Person, anderes Grundstück | Person matcht, Adresse nicht. | Eigenständiger Lead, Badge "Kontakt bekannt". | **ja** |

### Feld-Merge-Regel bei F3 [v3 — löst "der vollständigere gewinnt"]

Pro Feld einzeln, keine Datei-Ebene:

```
neuer Wert gefüllt   → neuer Wert gewinnt          (Korrektur schlägt Alt)
neuer Wert leer, alter gefüllt → alter Wert wird übernommen  (Lücke wird gefüllt)
beide leer           → leer
```

Damit gilt beides gleichzeitig: **der neueste Stand gewinnt bei Widerspruch, der
vollständigere gewinnt bei Lücken.** Kein Informationsverlust in keiner Richtung.
Jede übernommene Altangabe wird im Event `ersetzt` unter `merged_fields` protokolliert,
jede geänderte unter `changed_fields` mit alt/neu — nachvollziehbar auch dann, wenn
jemand versehentlich eine korrekte Nummer durch eine falsche ersetzt.

Der Vorgängerdatensatz wird **nie verändert und nie gelöscht**, nur umetikettiert
(`status='ersetzt'`, `superseded_by`). Archiv ist damit die Tabelle selbst.

### Match-Kriterien

- Person: `phone_e164` gleich **ODER** `email_normalized` gleich
- Grundstück: `street` + `city` gleich nach Normalisierung (lower, trim, collapse)
- Inhalt: `content_hash` über alle normalisierten Inhaltsfelder

### Korrektur-Flow ohne Edit-Link

Bestätigungsmail zeigt alle erfassten Daten und den Satz: "Stimmt etwas nicht?
Senden Sie das Formular mit den korrigierten Angaben einfach erneut ab — wir
übernehmen automatisch den neuesten Stand." F3 erledigt den Rest.

**Bekannte Grenze (Notizen):** Korrigiert jemand die Grundstücksadresse selbst und
hat keine Telefonnummer/E-Mail-Übereinstimmung, matcht F3 nicht → zwei aktive Leads.
Weich abgefangen durch F4-Badge. Ohne Raten nicht automatisierbar.

## 5. Bestätigungsmail [v2]

Inhalt (schlichtes, responsives HTML-Template, Brevo):
1. Bestätigung + Zusammenfassung aller erfassten Daten (Tabelle)
2. Korrektur-Hinweis (erneut absenden, s. §4)
3. Erwartungssetzung: "Unser Team meldet sich in der Regel am nächsten
   Werktag-Vormittag." Falls Erreichbarkeits-Wunsch angegeben: reflektieren
   ("Wir versuchen es nachmittags").
4. Statischer Kontaktblock (Telefonnummer als Platzhalter) + ein Link auf
   planecobuilding.de ("Mehr über uns und unsere Leistungen").
5. Kein Newsletter-Charakter: transaktionale Mail, ein Link, kein Angebots-Karussell.

Nicht umgesetzt (Scope): Hotline mit automatischer Umleitung auf freie Mitarbeiter —
Telefonanlagen-Thema, nicht kostenlos web-baubar. In Mail steht eine statische
Nummer; Routing ist Notizen-Punkt "bei Livegang: Rückrufwunsch-Button statt Hotline".

## 6. Dashboard [v2 präzisiert]

- Tabs: **Neu | In Bearbeitung | Erledigt | Alle**. duplicate/superseded/spam sind
  default ausgeblendet, Toggle "alles anzeigen".
- Zeile: Datum (Europe/Berlin), Name, Ort, Bundesland, Gebiet-Flag
  (● grün innerhalb / ● rot außerhalb / ● grau unbestimmt/prüfen), Kanal
  (utm_source, daneben heard_about), Status, assigned_to, Badges.
- Badges: "erneut angefragt am X" (F2), "vom Kunden aktualisiert am X" (F3),
  "Kontakt bekannt" (F4), "Telefon prüfen" (phone_valid=false), "Adresse mehrdeutig".
- Detailansicht: alle Felder, message prominent (Sales-Gesprächseinstieg),
  superseded-Kette ausgegraut darunter, Event-Historie, **Google-Maps-Link**
  aus lat/lon (kostenlos, kein API-Key — reiner Link maps.google.com/?q=lat,lon)
  als visueller Ein-Blick-Check fürs Sales-Team.
- Aktionen: Status ändern, assigned_to setzen, disqualify_reason, "Mail erneut
  senden", "Geocoding erneut", globaler Retry-Button.
- Sortierung: Default älteste unbearbeitete zuerst (Morgen-Workflow), umschaltbar.
- CSV-Export: Semikolon, UTF-8 BOM, Europe/Berlin, enthält alle Auswertungs- und
  Qualitätsspalten.

## 7. Auswertung im Dashboard [v3 — eigener Tab, ersetzt "nur CSV"]

Pflichtteil 6 verlangt beurteilen zu können, welche Kanäle Anfragen bringen **und
welche davon etwas taugen**. Das im Dashboard sichtbar zu machen statt nur im CSV
ist billig (eine SQL-Aggregation, eine Tabelle) und beantwortet die Anforderung direkt.

**Tab "Auswertung"** — eine Tabelle, gruppierbar über Dropdown nach:
`utm_source` | `utm_campaign` | `heard_about` | `Bundesland`

Spalten je Gruppe:

| Spalte | Aussage |
|---|---|
| Anfragen | Volumen |
| Qualifiziert / Disqualifiziert / Offen | Ergebnis |
| Qualifizierungsquote | "taugt der Kanal" |
| Eigentümer-Anteil | Lead-Güte vorab (Marcos Frage: kommen von Google mehr Eigentümer?) |
| Ø Zeit bis Erstkontakt | Prozessqualität (aus `contacted_at`, s. lead_events) |
| Telefon unlesbar % | Datenqualität je Kanal |
| Adresse unklar % | Datenqualität je Kanal |
| Spam % | Trafficqualität je Kanal |

Umsetzung: ein `GROUP BY` mit `FILTER`-Aggregaten, in Jinja als Tabelle gerendert.
Keine Charts, keine JS-Bibliothek — der Wert liegt in den Zahlen, nicht in Balken.
Zweite Ansicht: Kreuztabelle Kanal × Bundesland (Marcos Frage "welche Region wird
über welchen Weg besser erfasst"), ebenfalls reines GROUP BY.

**Ehrlichkeits-Hinweis im UI und in den Notizen:** Bei fünf Testleads sind alle Quoten
statistisch bedeutungslos. Die Ansicht zeigt eine Zeile "Basis: n Anfragen" und blendet
Quoten unter n=10 grau aus. Das ist kein Deko-Feature, sondern verhindert, dass
jemand aus zwei Datenpunkten eine Kanalentscheidung ableitet.

**Nicht gebaut:** Zeitreihen, Kohorten, Attributionsmodelle, Offline-Conversion-Upload
zu Google/Meta (Daten liegen via gclid/fbclid bereit — Notizen-Punkt).

## 8. Entscheidungen aus der Review-Runde [v2]

**K1 — Keine separate Wohnadresse der Person; Kontaktdaten bleiben Pflicht.**
Marcos Vorschlag "Personenangaben optional, nur Grundstück Pflicht" kollidiert mit
seinem eigenen Datenbank-Punkt (ohne Tel/E-Mail kein Kontaktweg → Lead wertlos)
und mit der Pflicht-Bestätigungsmail (braucht E-Mail) sowie dem Kernprozess
"wird anschließend vom Sales-Team kontaktiert" (braucht Telefon). Aufgelöst:
Name/E-Mail/Telefon Pflicht, als Adresse existiert NUR das Grundstück (Aufgabe
verlangt "Kontaktdaten + Adresse des Grundstücks", keine Wohnadresse). is_owner
deckt die Beziehung Person↔Grundstück ab, ohne sechs Adressfelder.

**K2 — Nichts wird gespeichert-und-weggeworfen.** Statt "leere Einträge wegwerfen":
Pflichtfelder werden client- UND serverseitig erzwungen; ein unvollständiger Submit
wird mit 422 abgelehnt und das Formular mit erhaltenen Eingaben re-rendert. Stilles
Verwerfen widerspräche Marcos eigenem "Daten nicht wegschmeißen"-Prinzip; ein
regulärer Nutzer kann den Fall gar nicht erzeugen, nur direkte Bot-POSTs.

**K3 — Vor-/Nachname-Vertauschung kann nicht auftreten.** Der klassische ETL-Fall
lautet: Es gibt zwei getrennte Spalten `vorname` und `nachname`, und jemand trägt
"Ahrens" in `vorname` und "Thomas" in `nachname` ein — dann steht in der Datenbank
etwas Falsches an einer definierten Stelle. Hier gibt es **ein einziges Feld `name`**,
in dem "Thomas Ahrens" als ganzer String steht (genau wie in den Beispieldaten der
Aufgabe). Es existiert keine Stelle, an der etwas vertauscht sein könnte, weil nichts
getrennt wird. Eine Erkennungs-Heuristik über Vornamenslisten würde bei Doppelnamen,
ausländischen Namen und Titeln danebenliegen und hätte keinen Nutzen: Sales begrüßt
mit dem vollen Namen, so wie er eingegeben wurde.

**K4 — Edit-Link verworfen, Korrektur läuft über erneutes Absenden (§4/F3).**
Ein signierter Edit-Link + zweites Formular + Token-Ablauf wäre 2-3h und ein
unauthentifizierter Zugriffspfad auf personenbezogene Daten. Die Dedup-Logik
liefert denselben Nutzen gratis. Edit-Link = Notizen-Punkt "nächster Schritt".

**K5 — Hotline nicht baubar im Rahmen** (s. §5).

**K7 — Entweder-E-Mail-oder-Telefon verworfen.** Marcos Vorschlag (nur ein Kontaktweg
Pflicht) erhöht die Conversion, kollidiert aber mit Pflichtteil 3: ohne E-Mail-Adresse
kann die geforderte automatische Bestätigungsmail nicht auslösen. Ein Lead ohne
Bestätigung wäre eine still ausbleibende Pflichtfunktion. Gewählt: E-Mail Pflicht,
Telefon optional — das ist zugleich die conversion-freundlichere Seite, weil in
Deutschland die Telefonnummer das Feld ist, an dem Interessenten zögern, nicht die
E-Mail. Alles andere ist optional (§3.1). Die Abwägung gehört in die Notizen.

**K8 — Statuswerte und Event-Typen auf Deutsch, Spaltennamen englisch.** Grund: Status
und Events landen 1:1 im Dashboard und im CSV-Export, den ein deutsches Sales-Team
liest — eine Übersetzungsschicht wäre eine zusätzliche Fehlerquelle ohne Nutzen.
Spalten- und Funktionsnamen bleiben englisch (Konvention, Bibliotheks-Interop).
Werte: `neu, kontaktiert, qualifiziert, disqualifiziert, duplikat, ersetzt, spam`;
Events: `erstellt, status_geaendert, zugewiesen, mail_gesendet, mail_fehlgeschlagen,
geocodiert, erneut_angefragt, ersetzt`.

**K6 — Mail bei jedem Submit-Vorgang** (Marcos Regel, §4) — ersetzt die alte
24h-Unterscheidung. Einfacher und kundenfreundlicher; interner Einmal-Kontakt ist
über die Führend-Logik gesichert.

## 9. Risikoanalyse (v1-Risiken R1-R15 gelten fort; neu:)

| # | Risiko | Umsetzung |
|---|---|---|
| R16 | content_hash zu streng (Leerzeichen/Groß-klein erzeugt "Korrektur" statt Duplikat) | Hash NUR über normalisierte Werte (lower, trim, collapse spaces, E.164). Unit-Tests mit Formatvarianten der Beispieldaten. |
| R17 | F3-Statusvererbung überschreibt Sales-Arbeit | Vererbung kopiert status/assigned_to/contacted_at auf den neuen Lead, Vorgänger wird nur umetikettiert. Kein Feld des Vorgängers wird verändert außer status+superseded_by. Test: contacted-Lead + Korrektur → neuer Lead ist contacted. |
| R18 | Kunde korrigiert E-Mail-Adresse → alte Adresse bekam Mail 1, neue bekommt Mail 2 | Gewollt: jede angegebene Adresse erhält Bestätigung ihres Vorgangs. Kein Handlungsbedarf, dokumentieren. |
| R19 | heard_about wird mit utm_source vermischt und verfälscht Auswertung | Getrennte Spalten überall (DB, Dashboard, CSV). Notizen: Selbstauskunft nie als Wahrheit über getaggte Kanäle stellen. |
| R21 | Feld-Merge (F3) übernimmt alte Werte, obwohl der Nutzer sie bewusst leeren wollte | Akzeptiert und dokumentiert: ein leeres Feld ist im Formular nicht von "nicht ausgefüllt" unterscheidbar. Sichtbar über `merged_fields` im Event; Sales sieht im Detail, welche Angabe aus einer früheren Anfrage stammt. |
| R22 | Auswertungs-Tab suggeriert Aussagekraft bei n=5 | Quoten unter n=10 werden ausgegraut, "Basis: n" immer sichtbar (§7). |
| R23 | Lead ohne Telefonnummer landet im Sales-Workflow, der auf Anrufe ausgelegt ist | Dashboard-Badge "nur E-Mail" + Ampel gelb; Sortierung stellt sie nicht hinten an. In Notizen: produktiv wäre eine eigene Mail-Vorlage für diesen Fall. |
| R20 | Formularlänge drückt Conversion | Bewusste Abwägung dokumentiert (§3.1), optionale Felder klar markiert, A/B-Test als Livegang-Schritt. |

## 10. Bewusst ausgeklammert (Notizen-Material)

- Kein LLM im Request-Pfad; kein Chart-Dashboard; keine users-Tabelle/Rollen;
  kein Double-Opt-In; keine Pagination (LIMIT 500); keine Kandidaten-Auswahl bei
  ambiguous (nur Anzeige); keine E-Mail-Tippfehler-Erkennung.
- Kein Edit-Link (K4), keine Hotline (K5), keine Namens-Heuristik (K3).
- Offline-Conversion-Upload zu Google/Meta: Daten liegen bereit (gclid/fbclid),
  Anbindung ist Livegang-Schritt.

## 11. Teststrategie [v2]

**Unit (pytest, pure functions ohne DB):** normalize_phone (alle 5 Beispielformate
→ erwartetes E.164), normalize_email, content_hash-Stabilität (Formatvarianten →
gleicher Hash; echte Änderung → anderer Hash), dedup_decision (F1-F4 als
Tabellentest), CSV-Zeile (Umlaute, Semikolon, BOM).

**E2E-Checkliste (manuell, Phase 5):** die fünf Beispielanfragen + je ein Fall
F1/F2/F3/F4 + Pflichtfeld-Reject mit erhaltenen Eingaben + Honeypot + Brevo-Key
absichtlich falsch → failed → Retry heilt + Mail-Inhalt prüft Datenzusammenfassung
+ Excel-Öffnung des CSV.

Kernlogik (Normalisierung, Hash, Dedup-Entscheidung) wird als reine Funktionen
geschnitten, damit sie ohne DB/HTTP testbar ist — nichts crasht stillschweigend,
weil jede Entscheidung einen benannten, getesteten Rückgabewert hat.

## 12. Offen vor Baustart

1. `heard_about`-Optionen final: Google-Suche / Google-Anzeige / Facebook oder
   Instagram / Empfehlung / Sonstiges.
2. Bestätigen: E-Mail Pflicht, Telefon optional (K7) — oder doch Entweder-oder mit
   dokumentierter Lücke bei der Bestätigungsmail.
3. Auswertungs-Tab: Umfang wie §7 oder schlanker (nur Gruppierung nach utm_source).

---

# Ergänzungen v4 (dritte Review-Runde)

## A. Auslandsanfragen: eigener Pfad [neu]

**Problem der Reihenfolge:** Beim Absenden ist noch nicht bekannt, ob die Adresse im
Ausland liegt — das Geocoding läuft danach (best effort/Retry). Die Bestätigungsmail
darf aber nicht warten.

**Lösung: zweistufig.**

1. Beim Absenden geht immer die normale Bestätigungsmail raus (Pflichtteil 3 erfüllt,
   unabhängig vom Geocoding-Ergebnis).
2. Ergibt das Geocoding `in_service_area=false` (Adresse eindeutig außerhalb
   Deutschlands), wird über denselben Retry-Pfad eine **zweite, andere Mail**
   ausgelöst: `ausland_hinweis_status` (offen/gesendet/fehlgeschlagen/nicht_noetig).
3. Lead bekommt `status='ausland'` (eigener Statuswert, eigener Dashboard-Filter),
   erscheint nicht in der normalen Sales-Warteschlange, geht aber nicht verloren.

**Inhalt der Auslandsmail (rechtlich vorsichtig formuliert):**
- Hinweis, dass die Leistung derzeit auf Deutschland beschränkt ist.
- Angebot, sich zu melden, sobald der Dienst im DACH-Raum verfügbar ist —
  als **aktive Zustimmung**, nicht automatisch: ein Antwort-Satz genügt, oder ein
  Häkchen bereits im Formular ("Bitte informieren Sie mich über neue Regionen").
- **Keine automatische Weitergabe an Partner.** Eine Datenweitergabe an ein
  Drittunternehmen braucht eine eigene Rechtsgrundlage (DSGVO Art. 6); die Zustimmung
  vom Standort-Check deckt sie nicht ab. Formulierung stattdessen: "Auf Wunsch
  vermitteln wir Sie an einen Partner vor Ort — antworten Sie einfach auf diese Mail."
  Damit entsteht die Einwilligung durch die Antwort des Interessenten.

Das ist zugleich ein guter Notizen-Punkt: erkannte Rechtsgrenze, sauber gelöst statt
ignoriert. Feld `expansion_opt_in boolean` im Formular (optional, unauffällig).

## B. Ampel: exakte Regeln und Anzeigetexte [neu]

Auswertung von oben nach unten, erste zutreffende Regel gewinnt.

| Prio | Bedingung | Ampel | Text im Dashboard |
|---|---|---|---|
| 1 | `is_spam = true` | ⚫ | "Spamverdacht: {spam_reason}" |
| 2 | `in_service_area = false` | 🔴 | "Außerhalb Deutschlands: {geo_state or geo_country}" |
| 3 | `geocode_status = 'nicht_gefunden'` | 🔴 | "Adresse im Kartendienst nicht gefunden" |
| 4 | `geocode_status = 'fehlgeschlagen'` | ⚪ | "Geocoding ausstehend (Dienst nicht erreichbar)" |
| 5 | `geocode_status = 'offen'` | ⚪ | "Prüfung läuft" |
| 6 | `geocode_status = 'entfaellt'` | ⚪ | "Geocoding entfällt (durch Korrektur ersetzt)" |
| 7 | `geocode_status = 'simuliert'` | ⚪ | "Geocoding simuliert (Testmodus, keine echte Prüfung)" |
| 8 | `geocode_status = 'mehrdeutig'` | 🟡 | "Adresse mehrdeutig: {n} mögliche Orte — im Gespräch klären" |
| 9 | `geocode_status = 'nur_ort'` | 🟡 | "Ort bestätigt, Straße nicht in der Karte gefunden" |
| 10 | `phone_e164 IS NULL` (kein Telefon angegeben) | 🟡 | "Nur per E-Mail erreichbar" |
| 11 | `phone_valid = false` | 🟡 | "Telefonnummer nicht lesbar: {phone_raw}" |
| 12 | `postal_code IS NULL` | 🟡 | "Keine PLZ angegeben — Ort per Geocoding bestätigt" |
| 13 | sonst | 🟢 | "Vollständig" |

Zeilen 6 und 7 [bei Implementierung ergänzt: 6 mit §G/Phase 4 Block (a),
2026-08-16; 7 mit Phase 4 Block (b), 2026-08-17, Fund s. docs/FUNDE.md -
beide fehlten zunächst in dieser Tabelle, obwohl der Code sie schon
kannte]. `entfaellt`: Vorgänger einer F3-Korrektur, dessen Geocoding noch
offen war (§G). `simuliert`: `DRY_RUN_GEOCODE=true`, kein echter
Nominatim-Aufruf.

Zeile 9 (`nur_ort`) [bei Implementierung ergänzt, 2026-08-18, Fund s.
docs/FUNDE.md]: eine der fünf Beispieladressen der Aufgabe ("Am
Mühlenteich 7, 23627 Groß Grönau") ist in OpenStreetMap auf Straßenebene
nicht erfasst, obwohl der Ort selbst sauber auflösbar ist. Statt das als
"nicht auffindbar" (Zeile 3, unterstellt einen Tippfehler) auszuweisen,
versucht `app/geocoding.py::geocode()` bei einer leeren Antwort MIT
Straße automatisch einen zweiten, strukturierten Versuch nur mit PLZ+Ort.
Gelingt der eindeutig, steht `geocode_status='nur_ort'` mit Bundesland/
Gemeinde/Koordinaten auf Ortsebene - gelb statt rot, weil Sales weiß,
woran es liegt (Kartendatenlücke, keine Falscheingabe), und trotzdem ein
Bundesland zum Einordnen hat. Zeile 3s Text zugleich präzisiert: "Adresse
nicht auffindbar — Schreibweise prüfen" unterstellte einen Fehler des
Interessenten, den die Untersuchung in genau diesem Fall widerlegt hat.

Grau (⚪) ist bewusst von Gelb getrennt: Gelb heißt "wir wissen etwas Unsicheres",
Grau heißt "wir wissen noch nichts". Sales soll graue Zeilen nicht als Problemfall
behandeln, sondern kurz später erneut schauen. Das gilt auch für `entfaellt`
(wird nie mehr geprüft, aber nicht wegen eines Datenproblems) und `simuliert`
(bewusst nicht geprüft, kein echtes Ergebnis vorhanden).

## C. Zweite Erweiterung: Bundesland → Landesbauordnung [neu, empfohlen]

**Was NICHT geht (recherchiert):** Es gibt keine bundesweite freie API für
Bebauungspläne oder Gebietstypen (WA/MI/GE). Bebauungspläne sind kommunal; jedes
Bundesland hat ein eigenes Geoportal, Bayerns Datensatz ist ausdrücklich nicht
flächendeckend. Ein Anbieter (kataster.dev) bündelt das kommerziell, ist aber
Waitlist/Early Access — als Abhängigkeit im Case unbrauchbar. **Würde man
"Gewerbegebiet" behaupten, ohne es sicher zu wissen, wäre das genau der stille
Fehler, den die Aufgabe sucht.**

**Was stattdessen — und fachlich stärker ist:** Nominatim liefert das Bundesland.
Planecos ganzes Geschäftsmodell hängt daran, dass Verfahrensfreiheit je Bundesland
verschieden geregelt ist (eigene Website: Bayern 75 m³ bei Tiny Houses, Garagen
30–50 m² je nach Land). Eine **statische Zuordnung Bundesland → Landesbauordnung**
(Name, Kurzhinweis, Link) gibt dem Sales-Team sofort den passenden Gesprächseinstieg.

- Umsetzung: ein Dictionary mit 16 Einträgen, kein API-Call, kein Ausfallrisiko.
- Anzeige in der Detailansicht: "Sachsen — SächsBO. Garagen bis 50 m² verfahrensfrei."
- Notizen: fachlicher Mehrwert ohne technische Abhängigkeit; Quelle und Stand
  dokumentiert, da Bauordnungen sich ändern.

**Optional, klar als unverbindlich markiert:** OpenStreetMap `landuse` über die
Overpass-API (kostenlos) gibt einen Hinweis wie "residential"/"industrial". Das ist
Crowdsourcing, nicht amtlich — deshalb nur als Zusatzzeile "OSM-Hinweis (unverbindlich):
Wohnbaufläche". Nur bauen, wenn Zeit übrig ist.

## D. E-Mail-Prüfung: was geht, was nicht [neu]

| Prüfung | Machbar | Umsetzung |
|---|---|---|
| Syntax (RFC-konform) | ja | `email-validator`, im Submit |
| Domain existiert / nimmt Mail an (MX-Record) | ja | `email-validator` mit `check_deliverability=True`, DNS-Lookup, ~100 ms |
| Tippfehler in bekannten Domains (gmial.com) | ja | Levenshtein gegen Liste der 20 häufigsten Domains → Hinweis im Formular "Meinten Sie gmail.com?", **kein Blocker** |
| Postfach existiert wirklich | **nein** | SMTP-Probing ist unzuverlässig, wird von Providern blockiert und gilt als missbräuchlich |

Der einzige echte Beweis ist die Zustellung selbst: `email_status='gesendet'` heißt
angenommen, `fehlgeschlagen` heißt Problem. Bounces würde Brevo per Webhook melden —
nicht gebaut, Notizen-Punkt.

## E. Wann KEINE Bestätigungsmail rausgeht [vollständige Liste]

Nur zwei Fälle:

1. **F1 technische Dopplung** (gleicher `submission_token`): war ein Absendevorgang,
   die Mail lief bereits.
2. **Spam erkannt** (Honeypot gefüllt oder Absenden < 3 s nach Formularaufruf):
   Bots bekommen keine Antwort, und die Brevo-Freigrenze (300 Mails/Tag) soll nicht
   von Bots aufgebraucht werden. Der Lead wird trotzdem gespeichert, damit ein
   False Positive im Dashboard sichtbar bleibt und manuell nachgesendet werden kann.

Alles andere (F2, F3, F4, jede Korrektur, jede erneute Anfrage) löst eine Mail aus.
Ein Retry einer fehlgeschlagenen Mail ist keine zweite Mail, sondern derselbe Versand.

## F. Schema-Ergänzungen v4

```sql
alter table leads add column expansion_opt_in boolean default false;
alter table leads add column geo_country text;                 -- ISO, für Auslandsfall
alter table leads add column ausland_hinweis_status text not null default 'nicht_noetig'
  check (ausland_hinweis_status in ('nicht_noetig','offen','gesendet','fehlgeschlagen'));
alter table leads add column traffic_light text;               -- abgeleitet, gecacht
alter table leads add column traffic_light_reason text;
-- status-check erweitern um 'ausland'
```

`traffic_light` wird bei jedem Schreibvorgang neu berechnet und gespeichert, damit
Sortierung und CSV-Export ohne Neuberechnung funktionieren. Die Ableitung liegt als
reine Funktion `ampel(lead) -> (farbe, grund)` vor und ist damit direkt testbar
(Tabellentest über alle 10 Regeln aus §B).

---

# Ergänzungen v5 (vierte Review-Runde)

## G. Verzögerte Verarbeitung: 1h Korrekturfenster [neu]

**Idee:** Nach dem Absenden geht sofort die Bestätigungsmail raus, aber Geocoding und
alle weiteren Nebenwirkungen warten eine Stunde. Sieht der Interessent in der Mail
einen Fehler und schickt korrigierte Daten, wird nur der korrigierte Datensatz
verarbeitet. Der Latenz-Spielraum ist da: das Sales-Team arbeitet morgens ab, nicht
in Echtzeit.

**Umsetzung:**
- Neue Spalte `process_after timestamptz not null default now() + interval '1 hour'`,
  Wert aus Env `PROCESS_DELAY_MINUTES` (Default 60).
- Der Cron/Retry verarbeitet nur Leads mit `process_after <= now()`.
- Die Bestätigungsmail bleibt sofort (sie ist die Voraussetzung dafür, dass der
  Interessent überhaupt korrigieren kann).
- Bei F3 (Korrektur): Vorgänger bekommt `geocode_status='entfaellt'`, seine anstehende
  Verarbeitung wird nicht mehr ausgeführt. Der neue Datensatz startet mit eigenem
  `process_after`.
- Dashboard zeigt für wartende Leads Ampel ⚪ "Korrekturfenster läuft bis HH:MM".

**Grenzfall (Notizen):** Korrigiert jemand erst nach Ablauf des Fensters, wurde der
alte Datensatz bereits geokodiert — der neue wird dann erneut geokodiert. Ein
zusätzlicher API-Call, kein Fehler.

**Warum das ein Urteilsvermögen-Punkt ist:** Bewusster Tausch von Latenz gegen
Ressourcen und Datenqualität, mit konkretem Grund (Bearbeitung am Morgen, Nominatim
ist rate-limitiert). Kein Feature, sondern eine Prozessentscheidung.

### Korrektur-Link mit Vorbefüllung

Die Bestätigungsmail enthält einen Link `/?k=<signiertes Token>`, der das Formular
mit den erfassten Daten vorbefüllt. Der Nutzer korrigiert nur das Falsche und sendet
ab — es ist derselbe Submit-Endpunkt wie immer, F3 übernimmt.

- Token: `itsdangerous.URLSafeTimedSerializer` über die `lead_id`, Gültigkeit 7 Tage.
- **Kein Bearbeitungs-Endpunkt**, kein Schreibzugriff über das Token — nur Vorbefüllung.
- Abwägung (Notizen): Wer den Link hat, sieht die Formulardaten. Der Link geht nur an
  die vom Interessenten selbst angegebene Adresse; Standardpraxis bei
  Buchungsbestätigungen. Ohne Vorbefüllung müsste er alles neu tippen — die
  Korrekturmöglichkeit wäre theoretisch.

## H. Kanal-Ableitung beim Speichern [neu; bei Implementierung präzisiert, 2026-08-15]

Statt die Herkunft erst in der Auswertung zusammenzurechnen, wird beim INSERT eine
saubere Spalte abgeleitet:

```
channel        text   -- google_ads | meta_ads | google_organisch | andere_suche |
                      -- empfehlung | direkt | sonstiges
channel_source text   -- woher die Ableitung stammt: utm | utm_unsicher | gclid |
                      -- fbclid | referrer | selbstauskunft | keine
```

Prioritätsreihenfolge (erste zutreffende gewinnt):

1. `utm_source` gesetzt → daraus ableiten, s. u. "utm_source-Zuordnung"
2. `gclid` vorhanden → `google_ads`, `channel_source='gclid'`
3. `fbclid` vorhanden → `meta_ads`, `channel_source='fbclid'`
4. `referrer` deutet auf Suchmaschine → daraus ableiten, `channel_source='referrer'`
   (Google → `google_organisch`, Bing/DuckDuckGo → `andere_suche`)
5. `heard_about` gesetzt → daraus ableiten, `channel_source='selbstauskunft'`
6. sonst → `direkt`, `channel_source='keine'`

**utm_source-Zuordnung, zweistufig:** Erst exakter Abgleich gegen eine kleine Liste
bekannter Plattform-Werte (`google` → `google_ads`, `facebook`/`meta`/`instagram` →
`meta_ads`), `channel_source='utm'`. Greift das nicht, ein Substring-Fallback mit
demselben Mapping, aber `channel_source='utm_unsicher'`. Grund: reines
Substring-Matching auf `google` würde auch bei `googlemail` oder einem
Kampagnennamen wie `google-partner-blog` zuschlagen — falsch, aber unauffällig
falsch. Der Fallback bleibt nützlich (eine unsichere Vermutung ist besser als
`sonstiges`), aber `channel_source` macht die Unsicherheit im Datensatz sichtbar
statt sie zu verstecken. Passt gar nichts, auch nicht als Substring →
`sonstiges`, `channel_source='utm'` (die Herkunft UTM ist ja gesichert, nur die
Plattform nicht).

Nutzen: Der Auswertungs-Tab gruppiert über eine einzige verlässliche Spalte, und
`channel_source` macht jederzeit prüfbar, wie sicher die Zuordnung ist. Eine per
gclid bestimmte Herkunft ist belastbar, eine per Selbstauskunft nicht — beides in
derselben Spalte zu mischen, ohne das kenntlich zu machen, wäre der klassische
stille Fehler in Marketing-Reports.

## I. Namens-Normalisierung [neu; Partikel-Regel korrigiert bei Implementierung, 2026-08-15]

Aus `TOM AHRENS` oder `tom ahrens` wird `Tom Ahrens`. Konservativ, mit Rohwert.

**Regel — normalisiert wird NUR, wenn der String komplett groß oder komplett klein
geschrieben ist UND keinen Namenspartikel enthält.** Gemischte Schreibweisen
bleiben unangetastet, weil dort echte Namensformen stecken: `McDonald`, `O'Brien`,
`di Marco`, `van der Berg`.

**Namen mit Namenspartikel werden grundsätzlich nicht normalisiert**, auch nicht
bei durchgängig Groß- oder Kleinschreibung: `von, van, de, del, di, da, der, den,
zu, zum, la, le, ter`. Beispiel: `van der berg` bleibt `van der berg`,
`name_normalized=false`. Grund: Ob ein Partikel am Satzanfang groß- oder
kleingeschrieben gehört, hängt vom Herkunftsland und Kontext ab (niederländisch
oft groß, deutsch fast nie) — das wäre Raten, und Raten ist nach CLAUDE.md Regel 12
ausgeschlossen.

*Korrektur-Notiz:* Die ursprüngliche Fassung dieses Abschnitts enthielt die Regel
"Namenspartikel bleiben klein, außer am Anfang" und nannte zugleich `van der Berg`
als Beispiel für eine Umwandlung — ein Widerspruch zur eigenen Ausnahme-Regel, der
erst beim Schreiben der Pflichttests auffiel. Aufgelöst zugunsten der strengeren,
konservativeren Variante: bei Partikeln lieber gar nicht normalisieren als raten.

Bei der Umwandlung (nur wenn kein Partikel enthalten ist):
- Bindestrich-Namen: beide Teile groß (`müller-lüdenscheidt` → `Müller-Lüdenscheidt`)
- Apostroph-Namen: Buchstabe danach groß (`o'brien` → `O'Brien`)
- Umlaute und ß unangetastet

Spalten: `name_raw` (wie getippt, nie verändert), `name` (Anzeigewert),
`name_normalized boolean`. Im Dashboard steht bei normalisierten Namen ein Hinweis
mit dem Originalwert. Getestet als Tabellentest über alle genannten Fälle plus
Negativfälle (gemischte Schreibweise und Partikel-Namen bleiben gleich).

## J. Spam: wie er sich äußert und was greift [neu]

Klarstellung: Leere Formulare sind kein Spamproblem — die scheitern an der
Pflichtfeldprüfung. Spam auf einem öffentlichen Formular sieht anders aus.

| Muster | Wie es aussieht | Gegenmaßnahme |
|---|---|---|
| Automatisiertes Ausfüllen | Bot liest das HTML und füllt **jedes** Feld mit plausiblem Müll, inklusive Adresse | **Honeypot**: ein per CSS verstecktes Feld (`website`), das kein Mensch sieht. Gefüllt → `is_spam=true` |
| Sofort-Absenden | Submit < 3 s nach Formularaufruf; Menschen tippen länger | Zeitschwelle über `form_rendered_at` |
| SEO-/Link-Spam | Anmerkungsfeld enthält URLs oder Werbetext | Link-Zähler im `message`-Feld: ≥2 URLs → Verdacht |
| Fremdschriftliche Massen-Bots | Kyrillisch/CJK im Anmerkungsfeld bei deutscher Adresse | Zeichensatz-Heuristik, nur als Verdachtsflag |

Alle vier setzen nur `is_spam` plus `spam_reason` — **es wird nie abgewiesen und nie
gelöscht.** Der Lead landet in einem eigenen Filter, damit ein False Positive
sichtbar bleibt und manuell freigegeben werden kann. Keine Bestätigungsmail
(Bots antworten nicht, und die Brevo-Freigrenze von 300 Mails/Tag soll nicht von
ihnen verbraucht werden).

**Ehrlich in den Notizen:** In den sechs Stunden Testbetrieb wird kein echter Spam
auflaufen, weil die URL nirgends verlinkt ist. Die Maßnahmen sind vorbeugend gebaut
und mit selbst erzeugten Fällen getestet, nicht im Feld erprobt.

## K. E-Mail-Prüfung: Client und Server [Ergänzung zu D]

- **Im Formular (sofort):** `type="email"` für die Browser-Prüfung, dazu ein
  JS-Check beim Verlassen des Feldes, der Tippfehler in bekannten Domains vorschlägt
  ("Meinten Sie gmail.com?"). Vorschlag, kein Blocker — der Nutzer kann ihn ignorieren.
- **Auf dem Server (verbindlich):** `email-validator` mit Syntax **und** MX-Prüfung.
  Die Clientprüfung ist Komfort, nie Sicherheit: ein direkter POST umgeht sie.

## L. Kontaktmöglichkeit auf der Formularseite [neu]

Im Fußbereich des Formulars und auf jeder Fehlerseite:
"Probleme mit dem Formular? Schreiben Sie an {KONTAKT_EMAIL} oder rufen Sie an unter
{KONTAKT_TELEFON}." Beides aus Env-Variablen.

Zusätzlich: Schlägt der Submit clientseitig fehl (Netzwerkfehler, Server nicht
erreichbar), zeigt das Formular denselben Kontakthinweis statt einer generischen
Browser-Fehlerseite. Grund: Ein Fehler, den niemand melden kann, bleibt unbemerkt —
und unbemerkte Fehler kosten Leads, die nie im System auftauchen.

## M. Schema-Ergänzungen v5

```sql
alter table leads add column process_after timestamptz not null
  default now() + interval '1 hour';
alter table leads add column name_raw text;
alter table leads add column name_normalized boolean not null default false;
alter table leads add column channel text;
alter table leads add column channel_source text;
-- geocode_status-check um 'entfaellt' erweitern
create index on leads (process_after) where geocode_status = 'offen';
```
