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

## Fehlendes `state`-Feld bei Stadtstaaten (`app/core/geocoding.py`)

Nominatims `address`-Objekt lieferte für Berlin und Hamburg gar kein
`state`-Feld, nur den ISO-3166-2-Code (z.B. `"ISO3166-2-lvl4": "DE-BE"`) -
`_extract_geo_state()` gab dort für einen ansonsten eindeutigen Treffer
still `None` zurück, `in_service_area` wäre für jeden Berliner oder
Hamburger Lead unbestimmt geblieben, obwohl die Adresse eindeutig in
Deutschland liegt. Bremen zeigte dasselbe Problem nicht durchgängig - eine
getestete Bremer Adresse lieferte `state: "Bremen"` direkt mit, was zeigt,
dass es keine feste Regel je Bundesland ist, sondern Nominatims/OSMs
uneinheitliche Datenpflege selbst innerhalb eines Bundeslands. Aufgefallen
ausschließlich beim Testen gegen die echte API (drei konkrete Adressen in
Berlin, Hamburg und Bremen abgefragt, die rohen `address`-Objekte
verglichen) - ein Fixture-basierter Unit-Test hätte das nie gezeigt, weil
Fixtures genau die Form annehmen, die man beim Schreiben des Tests
erwartet, nicht die Form, die die echte API tatsächlich liefert. Behoben
über eine Lookup-Tabelle aller 16 offiziellen ISO-3166-2:DE-Codes als
Rückfall, zusätzlich über ein neues Feld `geo_state_unresolved`, das
sichtbar macht, wenn selbst dieser Rückfall kein Bundesland liefert, statt
den Unterschied zwischen „nicht geprüft" und „geprüft, aber leer" zu
verwischen.

## `SERVICE_AREA_STATES=alle` wurde klaglos akzeptiert (`app/geocoding.py`)

Der Wert für `SERVICE_AREA_STATES` in der lokalen `.env` kam aus der
Einrichtungsanleitung, nicht aus dem Code, und lautete `alle` - naheliegend,
weil genau dieses Wort an anderer Stelle in der Anwendung (Tab-/Status-
Filter in `app/admin.py`) bereits „kein Filter" bedeutet. Die
Parsing-Funktion kannte diese Konvention aber nicht und behandelte jeden
nicht-leeren Wert als wörtliche, kommagetrennte Liste von Bundesland-Namen -
`SERVICE_AREA_STATES=alle` wurde so zur Ein-Element-Menge `{"alle"}`, auf
die kein echtes Bundesland je passt. Ergebnis: `in_service_area` wäre für
jede einzelne Adresse `False` gewesen, ganz ohne Fehlermeldung, was laut
Konzept direkt auf die rote Ampel „Außerhalb Deutschlands" abbildet - der
Fehler hätte sich also als scheinbar korrektes, nur negatives Ergebnis
getarnt. Aufgefallen beim Live-Test der Geocoding-Fixes, nicht beim
Schreiben des Codes, weil ein bekanntlich in Deutschland liegender Testfall
trotz korrekt aufgelöstem Bundesland als „außerhalb" markiert wurde. Eine
Konfiguration, die falsch sein kann, ohne dass irgendetwas abbricht, ist
dasselbe Muster wie die übrigen Funde in diesem Dokument. Behoben in zwei
Schritten: `alle` wird jetzt als Sentinel erkannt (wie in `app/admin.py`),
und zusätzlich wird jeder verbleibende Eintrag gegen die 16 echten
Bundesland-Namen geprüft - ein einzelner Tippfehler (z.B. `Bayen` statt
`Bayern`) hätte sonst genau denselben, unbemerkten Fehler reproduziert. Die
Prüfung läuft jetzt beim Modul-Import (wie `app/config.py` es für
`MAX_EMAILS_PER_DAY` bereits vormacht) und bricht den Prozessstart mit
einer Meldung ab, die den ungültigen Wert nennt, statt still auf eine leere
Menge zurückzufallen. Bestehende Datenbank-Zeilen waren nicht betroffen:
alle 19 Leads standen zum Zeitpunkt des Funds noch auf
`geocode_status='offen'` (Block (b), der einzige Aufrufer von `geocode()`,
war noch nicht gebaut) - es gab nichts zu korrigieren.

## `PROCESS_DELAY_MINUTES` ohne Wirkung (`app/submission.py`)

Von Anfang an in `.env.example` dokumentiert und in Konzept §G beschrieben,
aber nirgends gelesen: `process_after` bekam ausschließlich den
SQL-Spaltendefault (fest `now() + interval '1 hour'`), nie den Env-Wert. Der
Wert ließ sich ändern, ohne dass sich am Verhalten etwas änderte - dasselbe
Muster wie `SERVICE_AREA_STATES=alle`, eine dokumentierte, aber wirkungslose
Konfiguration. Aufgefallen erst beim Bauen von Phase 4 Block (b)
(Retry-Endpoint), weil bis dahin kein Code-Pfad `process_after` überhaupt
auswertete. Behoben: `app/config.py` liest `PROCESS_DELAY_MINUTES` jetzt
beim Modul-Import (bricht bei fehlendem Wert sofort ab, wie die übrigen
Kontingent-Werte), `_insert_lead()` setzt `process_after` explizit statt
sich auf den Spaltendefault zu verlassen - live verifiziert mit
`PROCESS_DELAY_MINUTES=0`.
