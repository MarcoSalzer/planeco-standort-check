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

## Eine korrekte Absicherung am falschen Ort legt das ganze Dashboard lahm (`app/core/ampel.py`, `app/admin.py`)

Beim Einführen von `geocode_status='simuliert'` (Migration 0007, Phase 4
Block b) wurde die Ampel-Regeltabelle (Konzept §B) nicht mitgezogen -
`ampel()` kennt nur die ihr beim Bauen bekannten Werte und wirft bewusst
einen `ValueError` bei allem Unbekannten, statt zu raten (CLAUDE.md Regel
3). Genau dieses richtige Verhalten wurde zum eigentlichen Problem: Marcos
Rückmeldung dazu trifft es genau - nicht der fehlende Statuswert selbst ist
interessant (ein triviales Nachziehen), sondern dass die Absicherung an der
falschen Stelle sitzt. `app/admin.py::dashboard` ruft `ampel()` in einer
Schleife über jede Zeile der Liste auf, ohne jede Isolierung zwischen
Zeilen - ein einziger Lead mit `geocode_status='simuliert'` (aus dem
eigenen Live-Test von Block b) brachte deshalb nicht nur diese eine Zeile,
sondern die komplette Lead-Liste mit einem 500er zum Absturz. Dieselbe
Absicherung in einer Funktion platziert, die einzeln pro Zeile aufgerufen
und abgefangen wird - etwa direkt in `_decorate_row` mit einem
Try/Except, das eine defekte Zeile auffällig, aber isoliert markiert -
hätte denselben fehlenden Wert nur als eine auffällige Zeile gezeigt, nicht
als Totalausfall. Aufgefallen durch Marco beim Öffnen des Dashboards, nicht
bei der Live-Verifikation von Block (b): dort wurden Retry-Endpunkt und
Datenbankzustand direkt geprüft, das Dashboard selbst aber nie geladen,
obwohl zu dem Zeitpunkt bereits mehrere eigene Testleads mit
`geocode_status='simuliert'` in der Datenbank standen - eine Lücke in der
eigenen Testtiefe, nicht nur im Code. Behoben: `simuliert` in `ampel()`
und Konzept §B ergänzt (grau, "Geocoding simuliert (Testmodus, keine echte
Prüfung)"). Zusätzlich, wichtiger als der Einzelfall:
`tests/test_status_constraints.py` prüft `ampel()` jetzt gegen JEDEN von
der echten CHECK-Constraint erlaubten `geocode_status`-Wert - gegen die DB
gelesen, nicht gegen eine von Hand gepflegte Liste, die genau auf dieselbe
Art still hätte veralten können wie die Regeltabelle selbst.

## `pyproject.toml` wurde als Projektdefinition statt als Pytest-Konfiguration gelesen (`pyproject.toml`, `pytest.ini`)

`pyproject.toml` existierte ausschließlich für `[tool.pytest.ini_options]`
(`pythonpath`/`testpaths`, seit dem Kernlogik-Commit vom 15.08.), ohne
`[project]`-Abschnitt - für pytest genügt das, da es das Vorhandensein der
Datei ohne Projektdefinition nie prüft. Vercels neuerer, `uv`-basierter
Python-Build behandelt die bloße Existenz von `pyproject.toml` dagegen als
"dieses Projekt erklärt seine Abhängigkeiten hier" und versucht `uv lock`
dagegen laufen zu lassen - das schlug fehl ("No `project` table found"),
weil kein `[project]`-Abschnitt existiert. Der Build brach damit komplett
ab, sichtbar ausschließlich im Vercel-Deployment-Log, nie lokal: `pytest`
braucht den `[project]`-Abschnitt nicht und lief die ganze Zeit
klaglos durch.

Naheliegend wäre gewesen, nur einen minimalen `[project]`-Abschnitt
nachzutragen, um den Fehler verschwinden zu lassen. Vor der Entscheidung
recherchiert (Vercel-Dokumentation, ein passender GitHub-Issue im
vercel/vercel-Repo mit identischem Fehlerbild bei anderen Nutzern): Sind
sowohl `pyproject.toml` als auch `requirements.txt` vorhanden und existiert
kein Lockfile, verwendet Vercels Build laut eigenem Log-Text ausdrücklich
NUR `pyproject.toml` ("Detected both pyproject.toml and requirements.txt
but no lockfile; using pyproject.toml") - `requirements.txt` würde dann
komplett ignoriert. Ein minimaler `[project]`-Abschnitt ohne
Abhängigkeitsliste hätte den jetzigen, lauten Baufehler durch einen
stilleren ersetzt: der Build wäre durchgelaufen, aber ohne eine einzige
der echten Abhängigkeiten (FastAPI, psycopg, ...) zu installieren - ein
sofortiger Laufzeitabsturz bei der ersten Anfrage statt eines
Deployment-Fehlers. Sicher wäre nur ein `[project.dependencies]`-Abschnitt
gewesen, der `requirements.txt` vollständig dupliziert, zusätzlich mit
einem committeten `uv.lock` - eine zweite Quelle der Wahrheit für
Abhängigkeiten, die genau auf die Art hätte auseinanderlaufen können wie
mehrere andere Funde in diesem Dokument.

Stattdessen die Ursache entfernt statt umgangen: Pytest-Konfiguration nach
`pytest.ini` verschoben (`[pytest]`-Sektion statt
`[tool.pytest.ini_options]`, sonst inhaltlich identisch), `pyproject.toml`
gelöscht. Kein Kompromiss, sondern eine Rückkehr zu einem bereits
nachweislich funktionierenden Stand: Das allererste erfolgreiche
Vercel-Deployment (Commit `8f70f2f`, FastAPI-Skelett) lief ausschließlich
über `requirements.txt` + `api/index.py` + `.python-version`, bevor
`pyproject.toml` einen Commit später überhaupt existierte. Live gegen ein
echtes Deployment noch nicht verifiziert (folgt mit dem nächsten Deploy),
lokal lief die volle Testsuite nach der Umstellung unverändert grün.

Bemerkenswert: derselbe Fundtyp wie der `vercel.json`-Fund vom ersten Abend
(Commit `80e85a4`, 15.08.) - dort brach der Build an einem ungültigen
`functions.runtime`-Feld ("python3.12" statt des für Custom-Runtimes
erwarteten `<paket>@<semver>`-Formats), hier an einer für ein anderes
Werkzeug angelegten Datei, die Vercel als Projektdefinition liest. Beide
Fehler sind ausschließlich beim Deployment sichtbar, keiner lokal
reproduzierbar - Vercels Build-Pipeline interpretiert Konfigurationsdateien
strenger und anders, als die Werkzeuge, für die sie eigentlich gedacht
sind.

## Blockweise Gruppen-Einfärbung war mit dem eigenen Standardfilter unvereinbar (`app/admin.py`, `admin_dashboard.html`)

Die "Blockweise Tönung" vom 17.08. (zusammengehörige Zeilen teilen sich
einen getönten Hintergrund) wurde gebaut und live geprüft, aber nur mit
`alle=1` - also mit eingeblendeten Duplikaten/Ersetzt-Zeilen. Im
STANDARDFILTER (der Normalfall: Duplikate/Ersetzt/Spam/Ausland
ausgeblendet) enthält jede Lead-Nummer-Gruppe zwangsläufig nur die eine
aktuell gültige Zeile - die zweite oder dritte Version, die die Tönung
erst als Gruppe erkennbar machen sollte, ist ja genau das, was der
Standardfilter wegblendet. Übrig blieb ein bedeutungsloses Zebramuster
über Einzelzeilen, dazu in Blau - einer Farbe, die als Hervorhebung liest,
nicht als Dämpfung, also das Gegenteil der beabsichtigten Wirkung. Aufgefallen
erst, als Marco die Liste als Export/Screenshots durchsah, nicht bei der
eigenen Live-Verifikation - die lief ausschließlich mit `alle=1`, dem
einzigen Modus, in dem die Tönung tatsächlich das zeigte, wofür sie gebaut
wurde. Derselbe blinde Fleck wie beim `geocode_status='simuliert'`-Fund:
gegen einen unvollständigen Satz an Zuständen getestet, nicht gegen den
tatsächlichen Standardfall.

Behoben durch Vereinfachung statt Reparatur: Die Tönung ersatzlos entfernt,
die bereits vorhandene `row-inaktiv`-Dämpfung (Duplikat/Ersetzt/Spam/
Ausland gedämpft, alles andere normal) übernimmt die Funktion allein - eine
Regel weniger im Kopf, nicht mehr.
