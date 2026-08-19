# Funde während der Implementierung

Arbeitsdokument für die Abgabe-Notizen (`NOTES.md`). Hält Fehler fest,
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
`main.py`s Formular-Parsing selbst. Betroffene Bestandszeilen mit
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
Menge zurückzufallen. Bestehende Datenbank-Zeilen waren nicht betroffen: sie
standen zum Zeitpunkt des Funds noch alle auf `geocode_status='offen'` (der
einzige Aufrufer von `geocode()` war noch nicht gebaut) - es gab nichts zu
korrigieren.

## `PROCESS_DELAY_MINUTES` ohne Wirkung (`app/submission.py`)

Von Anfang an in `.env.example` dokumentiert und in Konzept §G beschrieben,
aber nirgends gelesen: `process_after` bekam ausschließlich den
SQL-Spaltendefault (fest `now() + interval '1 hour'`), nie den Env-Wert. Der
Wert ließ sich ändern, ohne dass sich am Verhalten etwas änderte - dasselbe
Muster wie `SERVICE_AREA_STATES=alle`, eine dokumentierte, aber wirkungslose
Konfiguration. Aufgefallen erst beim Bauen des Retry-Endpunkts, weil bis
dahin kein Code-Pfad `process_after` überhaupt auswertete. Behoben:
`app/config.py` liest `PROCESS_DELAY_MINUTES` jetzt beim Modul-Import
(bricht bei fehlendem Wert sofort ab, wie die übrigen Kontingent-Werte),
`_insert_lead()` setzt `process_after` explizit statt sich auf den
Spaltendefault zu verlassen - live verifiziert mit `PROCESS_DELAY_MINUTES=0`.

## Eine korrekte Absicherung am falschen Ort legt das ganze Dashboard lahm (`app/core/ampel.py`, `app/admin.py`)

Beim Einführen von `geocode_status='simuliert'` wurde die Ampel-Regeltabelle
(Konzept §B) nicht mitgezogen - `ampel()` kennt nur die ihr beim Bauen
bekannten Werte und wirft bewusst einen `ValueError` bei allem Unbekannten,
statt zu raten (CLAUDE.md Regel 3). Genau dieses richtige Verhalten wurde
zum eigentlichen Problem: nicht der fehlende Statuswert selbst ist
interessant (ein triviales Nachziehen), sondern dass die Absicherung an der
falschen Stelle sitzt. `app/admin.py::dashboard` ruft `ampel()` in einer
Schleife über jede Zeile der Liste auf, ohne jede Isolierung zwischen
Zeilen - ein einziger Lead mit `geocode_status='simuliert'` (aus einem
eigenen Live-Test) brachte deshalb nicht nur diese eine Zeile, sondern die
komplette Lead-Liste mit einem 500er zum Absturz. Dieselbe Absicherung in
einer Funktion platziert, die einzeln pro Zeile aufgerufen und abgefangen
wird - etwa direkt in `_decorate_row` mit einem Try/Except, das eine
defekte Zeile auffällig, aber isoliert markiert - hätte denselben
fehlenden Wert nur als eine auffällige Zeile gezeigt, nicht als
Totalausfall. Aufgefallen beim Öffnen des Dashboards, nicht bei der
Live-Verifikation des Retry-Endpunkts selbst: dort wurden Retry-Endpunkt
und Datenbankzustand direkt geprüft, das Dashboard selbst aber nie
geladen, obwohl zu dem Zeitpunkt bereits mehrere eigene Testleads mit
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
(`pythonpath`/`testpaths`), ohne `[project]`-Abschnitt - für pytest genügt
das, da es das Vorhandensein der Datei ohne Projektdefinition nie prüft.
Vercels neuerer, `uv`-basierter Python-Build behandelt die bloße Existenz
von `pyproject.toml` dagegen als "dieses Projekt erklärt seine
Abhängigkeiten hier" und versucht `uv lock` dagegen laufen zu lassen - das
schlug fehl ("No `project` table found"), weil kein `[project]`-Abschnitt
existiert. Der Build brach damit komplett ab, sichtbar ausschließlich im
Vercel-Deployment-Log, nie lokal: `pytest` braucht den `[project]`-
Abschnitt nicht und lief die ganze Zeit klaglos durch.

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
Vercel-Deployment (FastAPI-Skelett) lief ausschließlich über
`requirements.txt` + `api/index.py` + `.python-version`, bevor
`pyproject.toml` einen Commit später überhaupt existierte. Lokal lief die
volle Testsuite nach der Umstellung unverändert grün.

Bemerkenswert: derselbe Fundtyp wie ein früherer `vercel.json`-Fund - dort
brach der Build an einem ungültigen `functions.runtime`-Feld ("python3.12"
statt des für Custom-Runtimes erwarteten `<paket>@<semver>`-Formats), hier
an einer für ein anderes Werkzeug angelegten Datei, die Vercel als
Projektdefinition liest. Beide Fehler sind ausschließlich beim Deployment
sichtbar, keiner lokal reproduzierbar - Vercels Build-Pipeline
interpretiert Konfigurationsdateien strenger und anders, als die
Werkzeuge, für die sie eigentlich gedacht sind.

## Blockweise Gruppen-Einfärbung war mit dem eigenen Standardfilter unvereinbar (`app/admin.py`, `admin_dashboard.html`)

Die "Blockweise Tönung" (zusammengehörige Zeilen teilen sich einen
getönten Hintergrund) wurde gebaut und live geprüft, aber nur mit `alle=1`
- also mit eingeblendeten Duplikaten/Ersetzt-Zeilen. Im STANDARDFILTER
(der Normalfall: Duplikate/Ersetzt/Spam/Ausland ausgeblendet) enthält jede
Lead-Nummer-Gruppe zwangsläufig nur die eine aktuell gültige Zeile - die
zweite oder dritte Version, die die Tönung erst als Gruppe erkennbar
machen sollte, ist ja genau das, was der Standardfilter wegblendet. Übrig
blieb ein bedeutungsloses Zebramuster über Einzelzeilen, dazu in Blau -
einer Farbe, die als Hervorhebung liest, nicht als Dämpfung, also das
Gegenteil der beabsichtigten Wirkung. Aufgefallen erst beim Durchsehen der
Liste als Export/Screenshots, nicht bei der eigenen Live-Verifikation -
die lief ausschließlich mit `alle=1`, dem einzigen Modus, in dem die
Tönung tatsächlich das zeigte, wofür sie gebaut wurde. Derselbe blinde
Fleck wie beim `geocode_status='simuliert'`-Fund: gegen einen
unvollständigen Satz an Zuständen getestet, nicht gegen den tatsächlichen
Standardfall.

Behoben durch Vereinfachung statt Reparatur: Die Tönung ersatzlos entfernt,
die bereits vorhandene `row-inaktiv`-Dämpfung (Duplikat/Ersetzt/Spam/
Ausland gedämpft, alles andere normal) übernimmt die Funktion allein - eine
Regel weniger im Kopf, nicht mehr.

## Eine der fünf Beispieladressen ist in OpenStreetMap auf Straßenebene nicht erfasst (`app/geocoding.py`, `app/core/ampel.py`)

Gemeldet wurden zwei Beobachtungen gleichzeitig: "Am Mühlenteich 7, 23627
Groß Grönau" (eine der fünf Beispieladressen aus der Aufgabenstellung)
landete auf `geocode_status='nicht_gefunden'`, und bei mehreren Hamburger
Adressen fehlte das Bundesland - letzteres klang nach einem Rückfall des
erst kürzlich gebauten Stadtstaaten-Fallbacks (s. den Fund oben zu
`_extract_geo_state()`). Bevor irgendetwas geändert wurde, wurde beides
anhand der rohen Nominatim-Antworten untersucht, nicht anhand einer
Vermutung.

**Hamburg: falscher Alarm, kein Rückfall-Defekt.** Live gegen die echte
API getestet: "Osterstraße 88, 22765 Hamburg" und "Alsterufer 1, 20354
Hamburg" lösen beide korrekt zu `geo_state='Hamburg'` auf, über exakt den
ISO-3166-2-Rückfall (`"ISO3166-2-lvl4": "DE-HH"`), der für diesen Fall
gebaut wurde. Zusätzlich über die gesamte Datenbank geprüft: kein
einziger Lead hatte `geocode_status='ok'` mit leerem `geo_state` - der
Rückfall griff also überall dort, wo er greifen sollte. Der konkrete Lead,
der vermutlich zu der Beobachtung geführt hatte (Alsterufer 1), stand auf
`geocode_status='simuliert'` (verarbeitet unter `DRY_RUN_GEOCODE=true`) -
dort wurde nie wirklich bei Nominatim angefragt, ein fehlendes Bundesland
ist in diesem Zustand das erwartete, dokumentierte Verhalten (Konzept §B
Zeile 7), kein Fehler. Verwechslungsgefahr: eine Zeile, die "noch nichts
weiß" (grau, Testmodus), sieht auf den ersten Blick ähnlich unvollständig
aus wie eine Zeile, die "etwas falsch ermittelt hat" (was hier gar nicht
vorlag).

**Groß Grönau: echter, reproduzierbarer Befund.** Live nachgestellt mit
exakt der strukturierten Abfrage der Anwendung
(`street="Am Mühlenteich 7", postalcode="23627", city="Groß Grönau",
countrycodes=de`): null Treffer, mit dem bereits reparierten Code - keine
veraltete Momentaufnahme. Aufgeschlüsselt durch gezielte Variation der
Parameter (nicht durch Raten):
- Nur `city="Groß Grönau"` + `postalcode="23627"` (ohne Straße) → 1
  Treffer, sauber als Dorf in Schleswig-Holstein aufgelöst. Der Ort selbst
  ist in Nominatims Daten also einwandfrei erfasst.
- Straße dazu (`street="Am Mühlenteich"`) → 0 Treffer, auch als
  vollständiger Freitext (`q="Am Mühlenteich 7, 23627 Groß Grönau"`).
- Bundesweite Freitextsuche nach "Am Mühlenteich" allein → 10 Treffer in
  Munster, Inden, Aachen, Trier, Rostock, Koblenz, Bochum und weiteren
  Orten - aber keiner in Groß Grönau.

Die Straße existiert also als Name in mehreren deutschen Orten, ist aber
für Groß Grönau selbst nicht in OpenStreetMap kartiert - eine echte
Datenlücke der Kartenquelle, kein Tippfehler des Interessenten und kein
Fehler in der strukturierten Abfrage (die Vermutung "Ortsnamen mit
Leerzeichen könnten die strukturierte Abfrage verwirren" ließ sich damit
ebenfalls widerlegen: "Groß Grönau" wird über den `city`-Parameter
anstandslos gefunden, das Leerzeichen ist nicht die Ursache).

**Konsequenz für die Ampel, nicht nur eine Randnotiz:** Der bisherige Text
bei `nicht_gefunden` ("Adresse nicht auffindbar — Schreibweise prüfen")
unterstellt einen Fehler des Interessenten - genau das widerlegt dieser
Fall. Ein Sales-Mitarbeiter, der diesen Text liest, würde vermutlich
versuchen, die Adresse nachzutippen oder anzurufen "ob die PLZ stimmt",
obwohl an der Eingabe nichts falsch war.

**Behoben durch einen zweiten Versuch statt durch Ausblenden.** Liefert
die strukturierte Abfrage MIT Straße null Treffer, unternimmt
`app/geocoding.py::geocode()` jetzt automatisch einen zweiten,
strukturierten Versuch NUR mit PLZ+Ort (1,1 s Pause dazwischen, dieselbe
Ratenbegrenzung wie zwischen zwei Leads im Batch - gilt pro Anfrage an
Nominatim, nicht nur pro Lead). Gelingt der eindeutig, bekommt der Lead
`geocode_status='nur_ort'` (Migration 0011) mit Bundesland, Gemeinde und
Koordinaten auf Ortsebene - beide Rohantworten (der leere Straßen-Versuch
UND das Ortsebene-Ergebnis) bleiben vollständig in `geocode_raw` erhalten,
nichts wird verworfen. Ampel dafür gelb statt rot: "Ort bestätigt, Straße
nicht in der Karte gefunden" (Konzept §B Zeile 9) - Sales sieht sofort,
woran es liegt, und hat trotzdem ein Bundesland zum Einordnen, statt vor
einem roten Fehler ohne Information zu stehen. Ist auch die Ortsebene
mehrdeutig oder ohne Treffer, bleibt der ursprüngliche `nicht_gefunden`-
Status unverändert stehen - ein unsicherer Rückfall wird nicht als
Ergebnis ausgegeben. Der bisherige `nicht_gefunden`-Text gleichzeitig
präzisiert: "Adresse im Kartendienst nicht gefunden", ohne die
Tippfehler-Unterstellung.

End-to-end gegen die echte Datenbank verifiziert (Insert + `geocode()` +
`apply_traffic_light()` in einer zurückgerollten Transaktion): Groß
Grönau ergibt `geocode_status='nur_ort'`, `geo_state='Schleswig-Holstein'`,
Ampel gelb mit dem neuen Text - keine Spuren in der Datenbank hinterlassen.

## Eine Reparatur erzeugte einen schlimmeren Fehler als den behobenen: der Auslandspfad war nie erreichbar, und der erste Fix dafür unscharf (`app/geocoding.py`, `app/core/geocoding.py`, `app/core/ampel.py`)

Der Auslandspfad (Konzept §A) wurde ausschließlich mit von Hand
konstruierten `GeocodeResult`-Objekten geprüft (`in_service_area=False`
direkt gesetzt, nie über einen echten Nominatim-Aufruf hergeleitet) -
dieselbe Annahme, aus der die Notwendigkeit des Auslandspfads überhaupt
entstand (Konzept §A geht von realen Auslandsadressen aus), wurde beim
Prüfen nie infrage gestellt. Die Abnahme-Checkliste sieht mit "Testadresse
in Österreich → rot + Auslandsmail" explizit einen Fall vor, der genau
das prüft - vor dieser Untersuchung war das nie gegen die echte
Nominatim-API gelaufen.

**Ursache gefunden: `app/geocoding.py::geocode()` schränkte jede Abfrage
auf `countrycodes=de` ein.** Damit konnte eine Adresse außerhalb
Deutschlands strukturell nie gefunden werden - nicht "falsch erkannt",
sondern gar nicht erst in der Ergebnismenge. Live geprüft: "Stephansplatz
1, 1010 Wien" und "Bahnhofstrasse 1, 8001 Zürich" lieferten mit
`countrycodes=de` beide null Treffer.

**Der erste Fix (Ländereinschränkung entfernen) erzeugte einen neuen,
schlimmeren Fehler.** Ohne `countrycodes=de` sucht Nominatim unscharf -
für "Stephansplatz 1, 1010 Wien" lieferte der (zu diesem Zeitpunkt noch
ungeprüfte) Ortsebene-Rückfall aus dem Fund oben einen Weiler namens
"Wien" bei Inzell, Bayern:
```json
{"hamlet": "Wien", "village": "Gschwall", "state": "Bayern",
 "postcode": "83334", "country_code": "de"}
```
Ergebnis vor der Korrektur: `geocode_status='nur_ort'`,
`geo_state='Bayern'`, `in_service_area=True` - eine österreichische Adresse
wurde als bestätigt innerhalb Deutschlands ausgewiesen, mit einem
erfundenen Bundesland. Reproduzierbar, kein Einzelfall: "Bahnhofstrasse 1,
8001 Zürich" landete ebenso unscharf in Nordrhein-Westfalen. **Das ist
schlimmer als der Ausgangszustand:** vorher ehrlich rot ("nicht
gefunden"), jetzt falsch gelb/grün mit einem Bundesland, das nicht
stimmt - ein stiller Fehler, den CLAUDE.md Regel 12 und die Aufgabe
insgesamt genau deshalb suchen, weil er sich als korrektes Ergebnis
tarnt statt als sichtbarer Fehlschlag.

**Zweite Korrekturrunde, zwei getrennte Fixe, beide nach demselben
Prinzip.** Der gemeinsame Nenner: eine Prüfung muss unterscheiden
zwischen "der Wert widerspricht der Eingabe" und "es gibt schlicht
keinen Wert". Beides gleich zu behandeln erzeugt falsche Negative (oder
hier: falsche Positive) - und dasselbe Muster trat im Verlauf der
Untersuchung bereits ein drittes Mal auf, nur unbemerkt: `app/core/
ampel.py` prüft "kein Telefon angegeben" bewusst über `phone_raw` statt
`phone_e164`, weil `normalize_phone()` bei jedem unlesbaren UND bei jedem
fehlenden Wert gleichermaßen `phone_e164=None` liefert - `phone_e164 IS
NULL` konnte "nichts eingetragen" nie von "etwas Unlesbares eingetragen"
unterscheiden, obwohl Konzept §B dafür zwei verschiedene Texte vorsieht.
Dieselbe Verwechslungsgefahr, drei verschiedene Felder (Telefon, jetzt PLZ
und Bundesland/Land), zufällig alle drei in diesem Fall aufgetreten.

1. **PLZ-Abgleich (`app/core/geocoding.py::parse_nominatim_results`):**
   Eine PLZ, die in Nominatims Antwort schlicht FEHLT (Verwaltungsgrenzen-
   Objekte wie Dörfer/Gemeinden liefern grundsätzlich keine - genau der Fall
   bei Groß Grönau oben), ist KEIN Widerspruch und verwirft den Treffer
   nicht. Eine PLZ, die tatsächlich ANDERS lautet, verwirft den Treffer
   ebenfalls nicht, macht die Abweichung aber sichtbar:
   `geocode_status='plz_abweichend'` (Migration 0012, neue Spalte
   `geo_postal_code` für die tatsächlich gefundene PLZ), Ampel gelb "PLZ
   weicht ab: eingegeben {X}, gefunden {Y}" statt Rot oder eines
   stillschweigend akzeptierten Treffers. Für den Bayern-Weiler bedeutet
   das: nicht mehr `nur_ort`/grün-artig bestätigt, aber auch nicht
   verworfen - sichtbar als Widerspruch, den Sales im Gespräch klärt.
2. **Land vor Bundesland (`app/core/geocoding.py`, `app/core/ampel.py`):**
   `in_service_area` wird jetzt PRIMÄR über `country_code` bestimmt, den
   Nominatim bei jeder Antwort mitliefert, unabhängig davon, ob ein
   `state`-Feld existiert. Ist das Land nicht `DE`, ist die Adresse
   außerhalb - unabhängig vom Bundesland. Erst wenn das Land `DE` ist (oder
   unbekannt), entscheidet weiterhin `SERVICE_AREA_STATES`. Das behebt
   nebenbei ein zweites, unabhängiges Problem: Wien liefert (wie die
   deutschen Stadtstaaten vor deren ISO-Rückfall) KEIN `state`-Feld, nur
   `"ISO3166-2-lvl4": "AT-9"` - eine rein deutsche Codetabelle
   (`ISO_3166_2_TO_STATE`) konnte das nie auflösen. Mit country_code als
   primärem Kriterium ist keine Codetabelle pro Land nötig.

Beide Korrekturen wieder live gegen die echte API verifiziert (Wien: `ok`,
`geo_country='AT'`, `in_service_area=False`; Zürich: unverändert korrekt,
da dort `state` direkt geliefert wird; Groß Grönau: `nur_ort` wieder
funktionsfähig; Hamburg mit einer bewusst falschen Test-PLZ:
`plz_abweichend` statt fälschlich `ok`). End-to-end mit einer
zurückgerollten Transaktion geprüft: eine Wien-Adresse durchläuft jetzt
tatsächlich `status='ausland'`, `ausland_hinweis_status='offen'`, die
zweite Mail lief simuliert durch - der Auslandspfad löst zum ersten Mal
über einen echten Nominatim-Aufruf aus, nicht nur mit konstruierten
Testdaten.

**Als Nebenbefund bestätigt, nicht neu behoben:** "Lindenweg 3, Neustadt"
ohne PLZ (Aufgabenbeispiel) ergab mit dem (zu diesem Zeitpunkt noch
gültigen) strengen Ortsnamen-Abgleich `nicht_gefunden` statt `mehrdeutig`,
weil keiner von Nominatims drei Kandidaten exakt "Neustadt" heißt (sondern
"Neustadt im Schwarzwald" usw.) - abgestimmt zunächst als richtiges
Verhalten eingestuft, bewusst nicht auf Teilstring-Toleranz aufgeweicht.
Diese Einschätzung erwies sich später selbst als Fehler, s. den Fund weiter
unten dazu.

## Ein Testfall überschrieb kurzzeitig einen echten Beispiel-Lead (`scripts/testlauf.py`, `app/submission.py`)

Beim automatisierten Testlauf über die Geocoding-Rückfälle, den
Auslandspfad und das Korrekturfenster verwendete ein neuer Testfall
versehentlich exakt dieselbe Adresse ("Am Mühlenteich 7, Groß Grönau") wie
ein echter Beispiel-Lead - eine der fünf Aufgaben-Beispieladressen, zu
diesem Zeitpunkt bereits in der Datenbank. `persist_submission()` erkennt
eine Straße+Ort-Übereinstimmung als F3-Match, unabhängig davon, ob der
Vorgänger ein echter Lead oder ein eigener Testdatensatz ist - aus Sicht
der Dedup-Logik gibt es diesen Unterschied nicht, und im Normalfall ist
das genau richtig so. Die Testabgabe wurde deshalb als Korrektur des
echten Leads behandelt: der echte Lead wurde auf `status='ersetzt'`
gesetzt, ein Fake-Testdatensatz wurde die neue führende Version.

Aufgefallen, weil das anschließende automatische Aufräumen des Testlaufs
(löscht nur selbst erzeugte Testzeilen) an einer Fremdschlüssel-Verkettung
scheiterte - nicht durch eine gezielte Prüfung, die den Fall hätte
verhindern sollen; die gab es zu diesem Zeitpunkt noch nicht.

**Vollständig von Hand wiederhergestellt**, bevor irgendetwas weiter
geändert wurde: status/superseded_by aus der Event-Historie rekonstruiert
(keine `status_geaendert`-Events auf dem echten Lead vorhanden, also
zweifelsfrei `status='neu'`/`superseded_by=NULL` vor dem Vorfall), das
fälschliche `ersetzt`-Event entfernt, der Fake-Testdatensatz gelöscht.
Verifiziert: die Kette steht exakt wie vor dem Testlauf, inklusive des
vorherigen legitimen `nur_ort`-Fixes auf demselben Lead. Kein Datenverlust,
aber knapp.

Derselbe grundsätzliche Fehlertyp wie die übrigen Funde in diesem Dokument,
nur mit echten Produktivdaten statt einer Fehlanzeige als Konsequenz: eine
für sich genommen korrekte Logik (F3-Matching über Adresse) traf auf einen
Kontext, den sie nicht kennt (Testdaten vs. echte Daten), und produzierte
ein stilles, folgenreiches Ergebnis - kein Fehlerausschlag, sondern eine
unbemerkt vertauschte Führungsrolle in einer Korrekturkette.

Behoben: `scripts/testlauf.py::_verify_address_free()` bricht jetzt vor
jedem risikobehafteten Testfall (und einmal zentral für den von ~15 Fällen
gemeinsam genutzten Default "Teststraße 1"/"Teststadt") hart ab, wenn die
Adresse bereits einem echten (nicht `testlauf-%`) Lead gehört, statt eine
Kollision einzugehen. Betroffene Testadressen auf eindeutig erfundene
Straßen in denselben Orten umgestellt. Die Absicherung wurde später ein
zweites Mal wirksam: sie brach einen weiteren Testlauf beim
Aufgabenbeispiel "Lindenweg 3, Neustadt" korrekt mit einer klaren
Fehlermeldung ab, weil dort inzwischen ein echter, über das Formular live
eingetippter Beispiel-Lead stand - ohne erneute Kollision.

## Eine Testerwartung meldete einen bereits behobenen Fehler als offenen Fund (`scripts/testlauf.py`)

`test_ungueltiger_heard_about()` prüfte noch gegen den Zustand von vor dem
Fix aus „heard_about ohne Server-Validierung" oben (Rohwert gespeichert,
`channel='sonstiges'`). Der Fix landete, die Testerwartung wurde dabei nicht
nachgezogen - das tatsächliche, korrekte Verhalten (`heard_about=None`,
`channel='direkt'`, Rohwert im Event `unerwarteter_feldwert` erhalten)
erschien dadurch in `docs/TESTLAUF.md` als offener Fund, obwohl es genau
der gewünschte, bereits gebaute Zustand war. Aufgefallen beim Gegenlesen vor
dem nächsten Testlauf, nicht durch eine Codeänderung. Derselbe Fehlertyp wie
beim `geocode_status='simuliert'`-Fund oben, nur einen Schritt weiter hinten
in der Kette: dort prüfte der Code gegen eine veraltete Handliste, hier
prüfte der Test gegen eine veraltete Erwartung - eine Prüfung, die nicht am
aktuellen Stand hängt, veraltet lautlos mit, unabhängig davon, ob sie im
Anwendungscode oder im Testcode steht. Testerwartung korrigiert
(`heard_about=None`, `channel='direkt'`, Event-Nachweis statt Rohwert-Nachweis).

## Env-Variable mit Trailing-Newline legte den Mailversand lahm (`app/mail.py`, alle Env-Lesestellen)

Beim Testen gegen die echte Vercel-Instanz schlug die Bestätigungsmail mit
`Illegal header value` fehl. Ursache: `BREVO_API_KEY` enthielt in Vercels
Env-Konfiguration einen Zeilenumbruch am Ende - vermutlich aus der
Zwischenablage beim Einfügen mitkopiert. `os.environ["BREVO_API_KEY"]` gab den
Wert unverändert inklusive `\n` zurück, `httpx` verweigerte den daraus gebauten
HTTP-Header mit genau dieser Meldung. Anders als bei den in diesem Dokument
bereits mehrfach behandelten Konfigurationsfunden (`SERVICE_AREA_STATES=alle`,
`PROCESS_DELAY_MINUTES` ohne Wirkung) war der falsche Wert hier nicht mal
optisch von einem korrekten zu unterscheiden - ein Zeilenumbruch am Ende
eines Copy&Paste-Werts ist in den meisten Eingabefeldern unsichtbar.

Der Wert wurde direkt in Vercel repariert, aber die eigentliche Lücke war
strukturell: JEDE Stelle im Code, die `os.environ` direkt liest, war für
denselben Fehlertyp anfällig, nicht nur `BREVO_API_KEY` - DATABASE_URL,
SESSION_SECRET, ADMIN_PASSWORD_HASH, EDIT_TOKEN_SECRET, RETRY_SECRET,
SERVICE_AREA_STATES, NOMINATIM_USER_AGENT, KONTAKT_EMAIL/-TELEFON und alle
Kontingent-Werte in `app/config.py` (11 Lesestellen über 6 Module). Ein
Trailing-Newline in `SESSION_SECRET` z.B. hätte nicht mal einen sichtbaren
Fehler erzeugt, sondern nur dazu geführt, dass Admin-Logins nach jedem
Neustart unterschiedlich signierte Cookies bekommen - ein stiller, schwer
zu diagnostizierender Fehler, derselbe Grundtyp wie die übrigen Funde in
diesem Dokument (eine falsche Konfiguration, die sich nicht sofort als
Fehler zeigt).

Behoben zentral statt punktuell: `app/env.py` mit `get_env()`/`require_env()`
- beide strippen jeden gelesenen Wert, bevor er den Aufrufer erreicht. Alle
Lesestellen in `app/config.py`, `app/db.py`, `app/mail.py`, `app/main.py`,
`app/geocoding.py`, `app/admin.py` darauf umgestellt, kein Modul liest
`os.environ` mehr direkt. Mit `monkeypatch.setenv` getestet (Whitespace/
Newline am Rand entfernt, interner Whitespace bleibt erhalten - z.B. eine
Telefonnummer mit Leerzeichen in `KONTAKT_TELEFON` darf nicht verstümmelt
werden). Nebenwirkung, erwähnenswert auch ohne unmittelbaren Handlungsbedarf:
falls `SESSION_SECRET` auf Vercel selbst einen Trailing-Newline enthält, wird
sie durch diesen Fix erstmals korrekt (gestrippt) gelesen - bereits
ausgestellte Admin-Sessions würden dadurch beim nächsten Deploy ungültig,
ein erneutes Login wäre nötig. Kein Datenverlust, nur ein einmaliger
Session-Reset.

## Ort- und PLZ-Feld vertauscht, Geocoding lief unbemerkt ins Leere (`app/core/validation.py`)

Beim Testen fiel auf: PLZ versehentlich ins Ortsfeld getippt, Ortsfeld
leer gelassen. `validate_submission()` verlangt PLZ ohnehin nicht (optional,
Konzept §3.1) und prüft `city` nur auf "irgendein Zeichen vorhanden" - eine
reine Ziffernfolge im Ortsfeld ist damit ein gültiger Submit. Nominatim
bekam als Ort z.B. "20095" statt "Hamburg" und fand strukturell nichts;
das Ergebnis wäre `nicht_gefunden` oder `nur_ort`-Rückfall ohne Straße
gewesen - dem Interessenten wie dem Sales-Team wäre nie aufgefallen, WARUM,
weil die Vertauschung selbst nirgends sichtbar gemacht wurde. Derselbe
Fehlertyp wie die übrigen Funde in diesem Dokument: ein falscher Zustand,
der sich als scheinbar normales (nur eben negatives) Ergebnis tarnt, statt
als das erkennbar zu werden, was er ist - eine Eingabevertauschung.

Behoben in `validate_submission()`: `city` wird zusätzlich auf eine reine
Ziffernfolge geprüft (`city.strip().isdigit()`) und mit 422 abgelehnt
("Ort besteht nur aus Ziffern - vielleicht sind Ort und PLZ vertauscht?"),
BEVOR das Geocoding je zu Gesicht bekommt, was falsch ist. Bewusst nur der
Extremfall (Ort = ausschließlich Ziffern), keine Heuristik, die auch
gemischte Fälle ("20095 Hamburg" in einem Feld) erkennen will - das wäre
Raten über die genaue Absicht des Interessenten (CLAUDE.md Regel 12).
Zwei Tests ergänzt: die Ziffernfolge wird abgelehnt, ein Ortsname mit
enthaltenen Ziffern (z.B. ein Nummernzusatz) bleibt zulässig.

## Die eigene Verschärfung des Ortsnamen-Abgleichs war selbst der Rückschritt (`app/core/geocoding.py`)

Der exakte Ortsnamen-Vergleich (Fund "Bayern-Weiler bei Wien", s. oben)
hatte eine echte Lücke geschlossen (ein zu großzügiger Abgleich
akzeptierte einen unscharf gefundenen falschen Ort), aber gleichzeitig
den eigentlichen Sinn eines der fünf Aufgabenbeispiele zerstört: "Lindenweg
3, Neustadt" soll laut Aufgabe `mehrdeutig` ergeben (Nominatim findet
"Neustadt" als Ortsnamen-Fragment in mehreren Bundesländern - Baden-
Württemberg, Schleswig-Holstein, Sachsen). Der exakte Vergleich verlangte
aber `"neustadt" == "neustadt im schwarzwald"` - das ist nie wahr, also
bestand kein einziger Kandidat den Ortsnamen-Filter, Ergebnis
`nicht_gefunden` statt `mehrdeutig`. Das fiel erst beim Live-Test mit dem
echten Formular auf, einen Tag nach der Einführung - die damalige
Testerwartung (`test_lindenweg_neustadt_mit_wortlaut_eingabe_
ist_jetzt_nicht_gefunden`) hatte das neue, aber falsche Verhalten korrekt
abgebildet und damit den Fehler mitbestätigt, statt ihn zu fangen (ein
Test kann nur falsch sein, wenn die Erwartung selbst falsch ist).

Derselbe grundsätzliche Fehlertyp wie beim Bayern-Weiler-Fund, nur mit
umgekehrtem Vorzeichen: dort war eine Prüfung zu locker (akzeptierte
Falsches), hier war die Korrektur zu streng (verwarf Richtiges). Beides
zeigt, dass "strenger ist sicherer" keine verlässliche Faustregel ist -
jede Verschärfung braucht dieselbe Sorgfalt wie jede Lockerung.

Behoben: Enthalten-Vergleich statt exaktem Vergleich (`app/core/geocoding.py::
_ort_enthalten()`) - einer der beiden normalisierten Werte muss im anderen
enthalten sein, in beide Richtungen. Löst den Neustadt-Fall (Eingabe ist
Präfix des Kandidaten) und bliebe auch für den umgekehrten Fall korrekt
(Kandidat ist Präfix der Eingabe). Der ursprüngliche Bayern-Weiler-Fund
bleibt weiterhin behoben: dort ging es um eine PLZ-Diskrepanz bei einer
unscharfen GEBIETSSUCHE ohne countrycodes-Filter, nicht um den
Ortsnamen-Vergleich selbst - "Wien" (Eingabe) vs. "Wien" (Weiler-Name im
Ergebnis) wäre auch mit dem alten exakten Vergleich schon eine
Übereinstimmung gewesen; PLZ/Land-Prüfung (nicht der Ortsname) fingen
diesen Fall auf und tun das unverändert weiter. Live gegen die echte API
erneut geprüft, ohne Datenbank-Schreibzugriff (die fünf echten
Beispiel-Leads standen zu dem Zeitpunkt bereits in der Datenbank):
Lindenweg/Neustadt wieder `mehrdeutig` (3 Kandidaten), Groß Grönau
weiterhin `nur_ort`, Hamburg mit falscher PLZ weiterhin `plz_abweichend`,
Wien weiterhin `ausland` - keiner der übrigen Fälle hat sich durch die
Lockerung verschlechtert.

## Row Level Security fehlte auf allen drei Tabellen (Supabase, `leads`/`lead_events`/`usage_counters`)

Supabase schickte eine automatische Sicherheitswarnung: Ohne Row Level
Security (RLS) sind Tabellen über die projekteigene REST-Schnittstelle
(PostgREST) lesbar und schreibbar - der dafür nötige `anon`-Schlüssel ist
aber ausdrücklich als öffentlicher Schlüssel gedacht (in einem
clientseitigen Supabase-Setup steht er üblicherweise sichtbar im
Frontend-Code). Diese Anwendung nutzt PostgREST nirgends - die
Verbindung läuft ausschließlich über den Transaction Pooler mit
`psycopg`/`DATABASE_URL` (CLAUDE.md, Supabase-Besonderheiten) - aber der
REST-Endpunkt existiert trotzdem automatisch als Teil jedes
Supabase-Projekts, unabhängig davon, ob die eigene Anwendung ihn
verwendet. Ohne RLS hätte jeder mit dem öffentlichen `anon`-Key die
komplette `leads`-Tabelle lesen und schreiben können - über einen
Zugriffsweg, der in keinem Anwendungscode vorkommt und deshalb bei einer
reinen Code-Durchsicht nie aufgefallen wäre.

Behoben: RLS auf allen drei Tabellen eingeschaltet. Verifiziert gegen die
echte Datenbank (read-only, `pg_class`/`pg_roles`/`pg_policies`):
`relrowsecurity=true` für `leads`, `lead_events`, `usage_counters`; die
Anwendung verbindet als Rolle `postgres` mit `rolbypassrls=true` - Owner-
Rollen umgehen RLS grundsätzlich, unabhängig von Policies, deshalb läuft
die Anwendung unverändert weiter. Es existiert aktuell keine einzige
RLS-Policy auf den drei Tabellen - in Kombination mit aktiviertem RLS
heißt das: jede Rolle, die (anders als `postgres`) RLS tatsächlich
unterliegt, wie die von PostgREST verwendeten `anon`/`authenticated`-
Rollen, wird jetzt vollständig abgewiesen, nicht nur eingeschränkt.

Muster: Eine Absicherung, die für den gewählten, tatsächlich genutzten
Zugriffsweg irrelevant aussieht, ist es für einen zweiten, unbeabsichtigt
offen gebliebenen Weg nicht. Anders als die übrigen Funde in diesem
Dokument liegt die Lücke hier nicht im Anwendungscode, sondern auf der
verwalteten Infrastruktur-Ebene (Supabase-Plattform) - dieselbe
Anwendung war die ganze Zeit korrekt, während parallel dazu ein zweiter,
von der Anwendung nie genutzter Zugriffsweg offen stand, den eine reine
Anwendungscode-Durchsicht nicht zeigen kann.

## F3 verlangte fälschlich nur die Adresse statt Person und Adresse (`app/core/dedup.py`)

Konzept §4 sieht für F3 (Korrektur) von Anfang an Person **und** Grundstück
vor. Die Implementierung prüfte die beiden Kriterien aber nicht gemeinsam,
sondern nacheinander in einer Reihenfolge, die das Konzept selbst
unterlief: `dedup_decision()` testete die Adresse zuerst und gab bei einem
Treffer sofort F3 zurück - die Personenprüfung (Telefon/E-Mail) wurde dann
gar nicht mehr erreicht. Eine Adressübereinstimmung allein reichte damit
aus, unabhängig davon, ob Name, Telefon und E-Mail komplett anders waren.

**Konkrete Folge:** Fragen zwei verschiedene Personen dasselbe Grundstück
an (zwei tatsächliche Interessenten für dieselbe Immobilie - kein
Kuriosum, sondern ein plausibler Alltagsfall für ein Standort-Check-
Formular), behandelte das System die zweite Anfrage wie eine Korrektur der
ersten: der neue Datensatz erbte automatisch `status`/`assigned_to`/
`contacted_at` der ersten Person, und der Datensatz der ersten Person
wurde `status='ersetzt'` - obwohl er inhaltlich weiterhin galt und zu einer
komplett anderen Person gehörte. Ein bereits kontaktierter oder
qualifizierter erster Interessent wäre dadurch aus der aktiven Sales-Liste
verschwunden, während die zweite, fremde Person unter seinem
Bearbeitungsstand auftauchte - ein stiller, folgenreicher Fehler in genau
der Kategorie, die dieses Dokument sammelt: kein Absturz, sondern ein
scheinbar plausibles, aber falsches Ergebnis.

Aufgefallen nicht beim Bauen, sondern bei einer gezielten Nachfrage: "Was
passiert, wenn zwei verschiedene Personen dasselbe Grundstück anfragen?" -
eine Frage, die sich beim Schreiben des Codes nicht gestellt hatte, weil
die Beispieldaten und Testfälle bislang ausschließlich denselben
Interessenten korrigieren oder erneut anfragen ließen, nie zwei
verschiedene Personen an derselben Adresse.

**Behoben durch einen eigenen fünften Fall statt einer Sonderbehandlung
innerhalb von F3:** F5 "Grundstück bekannt" - Adresse matcht, Person
nicht → eigenständiger neuer Lead mit eigener Lead-Nummer, kein Merge,
kein Erben von Bearbeitungsstand, keine `superseded_by`-Verkettung, nur
ein Dashboard-Badge mit Verweis auf die andere Anfrage (symmetrisch zu F4,
"Kontakt bekannt": dort matcht die Person, aber nicht die Adresse). F3
verlangt seitdem beide Kriterien gemeinsam, nicht mehr in einer
Reihenfolge, die eines der beiden faktisch überspringen konnte.

Bestehende Demo-Daten read-only geprüft, bevor der Fix als unbedenklich
galt: beide vorhandenen `superseded_by`-Ketten hatten in jedem Schritt
sowohl identische Adresse als auch identische Person (E-Mail) - beide
bleiben unter der strengeren Regel korrekt F3. Kein Fall von zwei
verschiedenen Personen an derselben Adresse existierte in den Demo-Daten;
nichts musste nachträglich korrigiert werden. Das ändert nichts daran,
dass der Fehler in echtem Betrieb - mit echten, unabhängigen Interessenten
- aufgetreten wäre.
