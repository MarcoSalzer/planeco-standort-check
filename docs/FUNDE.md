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
