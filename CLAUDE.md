# Projekt: Standort-Check (Planeco Case Study)

Lead-Capture-Anwendung: öffentliches Formular → Datenbank → Bestätigungsmail →
internes Dashboard. Bewertet wird nicht Featureumfang, sondern Sorgfalt,
Urteilsvermögen und Ehrlichkeit über Schwachstellen.

**Das vollständige Konzept steht in `docs/KONZEPT.md`. Lies es vor jeder
Implementierungsentscheidung. Weiche nicht davon ab, ohne es vorher anzusprechen.**
Der Umsetzungsplan steht in `docs/TODO.md`.

## Stack

- Python 3.12, FastAPI, Jinja2 Templates (kein separates Frontend-Framework)
- Supabase Postgres, Zugriff über `psycopg` mit Connection String aus Env
- Vercel Serverless (Python Runtime)
- Brevo für Transaktionsmails (HTTP-API, kein SMTP)
- Nominatim/OpenStreetMap fürs Geocoding
- pytest für die Kernlogik

## Harte Regeln

1. **Keine Secrets im Repo.** Alle Zugangsdaten aus `os.environ`. `.env` steht in
   `.gitignore`, `.env.example` enthält nur leere Platzhalter.
2. **Der Submit darf nie an einer Nebenwirkung scheitern.** Mail und Geocoding laufen
   in try/except mit Timeout ≤3 s. Schlägt etwas fehl, wird ein Statusfeld gesetzt
   und die Danke-Seite trotzdem ausgeliefert. Der einzige Vorgang, der den Submit
   abbrechen darf, ist der Datenbank-INSERT selbst.
3. **Kein `except: pass` und kein stilles Verschlucken.** Jeder gefangene Fehler wird
   entweder in einem Statusfeld, in `lead_events` oder im Log festgehalten. Wenn ein
   Zustand nicht behandelt werden kann, wirf eine Exception mit klarer Meldung statt
   einen Defaultwert zu erfinden.
4. **Keine Daten verwerfen.** Rohwerte (`phone_raw`, ursprüngliche Eingaben) bleiben
   unverändert erhalten. Ersetzte Datensätze werden umetikettiert und verkettet,
   nie gelöscht oder überschrieben.
5. **Kernlogik als reine Funktionen.** Normalisierung, `content_hash`,
   Duplikat-Entscheidung, Feld-Merge und Ampel-Ableitung liegen in eigenen Modulen
   ohne Datenbank- oder HTTP-Zugriff, damit sie ohne Mocks testbar sind.
6. **Statuswerte und Event-Typen sind deutsch** (`neu`, `kontaktiert`, `ersetzt`,
   `mehrdeutig` ...), Spalten-, Funktions- und Variablennamen englisch.
   Grund: Status landet 1:1 im CSV, das ein deutsches Sales-Team liest.
7. **Zeit:** In der Datenbank immer `timestamptz` in UTC. Anzeige im Dashboard und im
   CSV-Export in `Europe/Berlin`. Nie naive datetimes.
8. **CSV-Export:** Semikolon als Trennzeichen, UTF-8 **mit BOM**. Ohne beides zerlegt
   deutsches Excel die Datei.
9. **Kein LLM-Aufruf im Anwendungscode.** Die Anwendung läuft ohne KI-Abhängigkeit.
10. **Verzögerte Verarbeitung.** Die Bestätigungsmail geht sofort raus, Geocoding und
    alle weiteren Nebenwirkungen erst nach `process_after` (Default 1 Stunde). Der
    Retry-Endpunkt filtert immer auf `process_after <= now()`.
11. **Clientseitige Prüfungen sind Komfort, nie Sicherheit.** Jede Validierung im
    Browser existiert zusätzlich serverseitig. Ein direkter POST muss dieselben
    Prüfungen durchlaufen.
12. **Normalisierung nur konservativ.** Wenn eine Umwandlung raten müsste, wird nicht
    umgewandelt. Der Rohwert bleibt immer erhalten und wird im Dashboard sichtbar
    gemacht, wenn normalisiert wurde.

## Vercel-Besonderheiten

- Keine verlässlichen Background-Tasks nach der Response. `BackgroundTasks` aus
  FastAPI ist hier nicht verlässlich — nicht darauf bauen.
- Alles, was länger dauert oder scheitern kann, bekommt ein Statusfeld und wird über
  `POST /admin/retry` nachgeholt (ausgelöst per Dashboard-Button und
  GitHub-Actions-Cron alle 15 Minuten).
- Kein lokaler Dateizustand zwischen Requests.

## Supabase-Besonderheiten

- Verbindung läuft über den **Transaction Pooler** (Port 6543), nicht über die
  Direktverbindung.
- Der Transaction Pooler unterstützt **keine Prepared Statements**. In psycopg muss
  die Verbindung mit `prepare_threshold=None` geöffnet werden, sonst treten
  sporadische Fehler auf, die lokal (Direktverbindung) nicht auftauchen.
- Verbindungen werden pro Request geöffnet und geschlossen, kein globaler Pool im
  Modulzustand — Serverless-Instanzen werden ohne Vorwarnung beendet.

## Tests

`pytest` muss vor jedem Commit grün sein. Pflichttests:

- `normalize_phone` gegen alle fünf Telefonformate aus der Aufgabe
  (`+49 40 / 123 456`, `0170 5551234`, `040 55512345`, `004940123456`,
  `0451 9988776`) → erwartete E.164-Werte
- `content_hash`: Formatvarianten desselben Inhalts ergeben denselben Hash,
  echte Änderung ergibt einen anderen
- `dedup_decision`: Tabellentest über F1 bis F4 aus dem Konzept
- `merge_fields`: neuer Wert gewinnt / leerer neuer Wert übernimmt alten / beide leer
- `ampel`: Tabellentest über alle Regeln aus Konzept §B
- `normalize_name`: `TOM AHRENS` → `Tom Ahrens`, `müller-lüdenscheidt` →
  `Müller-Lüdenscheidt`; Namen mit Namenspartikel (von, van, de, del, di, da, der,
  den, zu, zum, la, le, ter) werden nie normalisiert — `van der berg` bleibt
  `van der berg`, `name_normalized=false` (Groß-/Kleinschreibung von Partikeln am
  Anfang hängt vom Herkunftskontext ab, das wäre Raten, s. Regel 12); `McDonald`
  und `O'Brien` bleiben bei gemischter Schreibweise ebenfalls unverändert
- `derive_channel`: Prioritätsliste aus Konzept §H, je ein Fall pro Stufe

## Arbeitsweise

- Kleine, thematisch klare Commits mit aussagekräftiger Message. Keine
  Sammel-Commits über mehrere Phasen.
- Nach jeder Phase aus `docs/TODO.md` kurz zusammenfassen, was gebaut wurde und was
  offen blieb — dieses Material fließt am Ende in `NOTES.md`.
- Wenn eine Anforderung im Konzept mehrdeutig ist: nachfragen statt annehmen.
  Getroffene Annahmen immer explizit benennen.
- Nach jeder neuen Abhängigkeit in `requirements.txt`/`requirements-dev.txt`: sofort
  in `.venv` installieren (`pip install -r requirements-dev.txt`) und verifizieren,
  dass die Anwendung startet — nicht nur die Datei ändern. Dasselbe `.venv` im
  Projektverzeichnis verwenden, nicht ein Wegwerf-venv unter anderem Namen, sonst
  bleibt die Prüfung folgenlos für die Umgebung, die tatsächlich benutzt wird.
