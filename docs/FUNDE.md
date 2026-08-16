# Funde während der Implementierung

Arbeitsdokument für die Abgabe-Notizen (`NOTES.md`, Phase 6). Hält Fehler fest,
die beim Bauen auftraten und deren Ursache — nicht das, was von Anfang an
funktioniert hat.

## `load_dotenv()`-Reihenfolge in `app/main.py`

`app/main.py` importierte `app.mail` — und damit transitiv `app.config`, das
`MAX_EMAILS_PER_DAY`/`MAX_GEOCODE_PER_MINUTE` beim Modul-Import sofort aus
`os.environ` liest — *vor* dem eigenen `load_dotenv()`-Aufruf. Ein Prozessstart
ohne bereits im Shell-Environment gesetzte Variablen crashte deshalb schon
beim Import, obwohl `.env` die Werte enthielt; lokal fiel das nicht auf, weil
im selben Terminal vorher schon erfolgreich mit Python gegen `.env` getestet
worden war und die Variablen dadurch bereits im Shell-Environment standen —
erst eine gezielte Simulation mit ausgeblendeten Variablen (`env -u ...`)
deckte es auf.

## Fehlende Logging-Konfiguration für `DRY_RUN_EMAIL`

Der Dry-Run-Log (`app.mail.dry_run`, Level INFO) blieb ohne explizites
`logging.basicConfig()` unsichtbar, weil Pythons Root-Logger standardmäßig auf
WARNING steht und INFO-Meldungen ohne Handler-Konfiguration verwirft. Lokal
nicht aufgefallen, weil Uvicorns eigene Start- und Access-Logs — separat von
Uvicorn selbst konfiguriert — im Terminal sichtbar blieben und so den Eindruck
erweckten, Logging funktioniere insgesamt normal.

## is_spam-Sync bei manuellem Status-Wechsel (`app/admin.py`)

Die Logik, die `is_spam` beim manuellen Setzen/Freigeben von `status='spam'`
mitzieht, prüfte zunächst `status != row["status"]` statt den eingereichten
Wert direkt — bei einem Alt-Lead, dessen `status` schon vor dem
Spam/Dedup-Fix bei `'neu'` hängengeblieben war (obwohl `is_spam=true`), war
eine Freigabe über genau diesen Status also keine *Änderung*, und `is_spam`
blieb fälschlich `true`. Aufgefallen erst beim Live-Test gegen einen echten
solchen Alt-Lead aus der Datenbank, nicht beim Schreiben des Codes selbst.

## heard_about ohne Server-Validierung (`app/core/validation.py`)

`validate_submission()` prüfte `contact_time_preference` gegen eine feste
Werteliste, `heard_about` trotz identisch fester Optionsliste im Formular
aber gar nicht — ein direkter POST mit einem beliebigen Wert ging klaglos
durch und landete unverändert in der Spalte. Aufgefallen erst beim
systematischen Testlauf über Randfälle (`scripts/testlauf.py`,
`docs/TESTLAUF.md`), nicht beim Schreiben von `validate_submission()`
selbst, wo die Asymmetrie zwischen den beiden gleich aussehenden
Select-Feldern nicht auffiel. Behoben: unbekannter Wert wird als „keine
Angabe" behandelt statt abgewiesen, Rohwert bleibt im Event
`unerwarteter_feldwert` erhalten (`app/core/normalize.py`,
`normalize_heard_about`).

## Leere Strings statt NULL in den Attributionsfeldern (`app/main.py`)

`heard_about`/`phone`/`name` wurden beim Submit explizit von leerem String
auf `None` normalisiert, die neun Attributionsfelder (`utm_*`, `gclid`,
`fbclid`, `referrer`, `landing_page`) nicht — das Hidden-Formularfeld
sendet bei fehlendem UTM-Parameter `value=""` statt gar keinen Wert.
Aufgefallen erst beim Bauen des Auswertungs-Tabs, wo `''` und `NULL` als
zwei optisch identische, aber tatsächlich getrennte „(keine Angabe)"-
Gruppen in derselben Auswertung erschienen, nicht beim Schreiben von
`main.py`s Formular-Parsing selbst. 15 betroffene Bestandszeilen mit
`migrations/0005_null_statt_leerstring_attribution.sql` bereinigt.
