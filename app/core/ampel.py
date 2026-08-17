"""ampel: Ableitung der Bearbeitbarkeits-Ampel für eine Lead-Zeile (Konzept §B).

Reine Funktion ohne DB-/HTTP-Zugriff (CLAUDE.md Regel 5), damit sie per
Tabellentest über alle Regeln aus §B geprüft werden kann. Seit Phase 4
Block c NICHT mehr beim Lesen aufgerufen, sondern ausschließlich von
app/traffic_light.py::apply_traffic_light() - einmal bei jedem
Schreibvorgang, der eine ampel-relevante Spalte ändert (Submit,
Geocoding-Ergebnis, manueller Statuswechsel, Spam-Freigabe, F3-Korrektur).
Das Ergebnis landet in den Spalten `traffic_light`/`traffic_light_reason`,
Liste und Detailansicht lesen nur noch diese Spalten.

Drei Abweichungen von der wörtlichen Regelformulierung in §B, mit Marco
abgestimmt (2026-08-16/17):

- Regeln 10/11 (Nummerierung nach Konzept §B seit dem 'nur_ort'-Zusatz,
  2026-08-18) prüfen `phone_raw` statt `phone_e164` auf "kein Telefon
  angegeben". `normalize_phone` liefert `phone_e164=None` bereits immer
  dann, wenn `phone_valid=False` ist - auch wenn gar nichts eingegeben
  wurde. "phone_e164 IS NULL" kann "nichts eingetragen" also nicht von
  "etwas Unlesbares eingetragen" unterscheiden, obwohl §B dafür zwei
  verschiedene Texte vorsieht (Regel 10 zeigt bewusst den Rohwert). Mit
  `phone_raw` bleibt die Unterscheidung erhalten.
- `geocode_status='entfaellt'` (Konzept §G) und `geocode_status='simuliert'`
  (DRY_RUN_GEOCODE) fehlten zunächst in der §B-Tabelle, obwohl der Code
  (bzw. die DB-Constraint) sie schon kannte - zu 'simuliert' s. den Fund in
  docs/FUNDE.md: genau diese Lücke ließ die komplette Lead-Liste mit einem
  ValueError abstürzen, sobald ein einziger Lead diesen Status trug. Beide
  jetzt nachgezogen, Tabelle und Code stimmen wieder überein.
- `geocode_status='nur_ort'` (2026-08-18, nach dem OSM-Fund in docs/FUNDE.md
  zur Straße "Am Mühlenteich" in Groß Grönau) neu ergänzt: Migration 0011,
  Rückfall-Logik in app/geocoding.py::geocode(). 'nicht_gefunden'-Text
  gleichzeitig präzisiert (kein unterstellter Tippfehler mehr).
"""
from dataclasses import dataclass

from app.core.spam import SPAM_REASON_LABELS


@dataclass(frozen=True)
class AmpelResult:
    farbe: str  # gruen | gelb | rot | grau | schwarz
    grund: str


def ampel(
    *,
    is_spam: bool,
    spam_reason: str | None,
    in_service_area: bool | None,
    geocode_status: str,
    geo_state: str | None,
    geo_country: str | None,
    geocode_candidate_count: int | None,
    phone_raw: str | None,
    phone_valid: bool,
    postal_code: str | None,
) -> AmpelResult:
    if is_spam:
        grund = SPAM_REASON_LABELS.get(spam_reason, spam_reason) if spam_reason else None
        return AmpelResult("schwarz", f"Spamverdacht: {grund}" if grund else "Spamverdacht")

    if in_service_area is False:
        ort = geo_state or geo_country or "unbekannt"
        return AmpelResult("rot", f"Außerhalb Deutschlands: {ort}")

    if geocode_status == "nicht_gefunden":
        # Marco, 2026-08-18, nach der OSM-Untersuchung in docs/FUNDE.md:
        # "Schreibweise prüfen" unterstellt einen Tippfehler des
        # Interessenten - bei einer echten Datenlücke im Kartendienst
        # (wie bei "Am Mühlenteich 7, Groß Grönau") war die Schreibweise
        # korrekt, nur OSM kennt die Straße nicht. Text jetzt neutral,
        # ohne diese Unterstellung.
        return AmpelResult("rot", "Adresse im Kartendienst nicht gefunden")

    if geocode_status == "nur_ort":
        # Konzept-Erweiterung (Marco, 2026-08-18): Rückfall-Ergebnis von
        # app/geocoding.py, wenn die strukturierte Abfrage MIT Straße
        # nichts fand, aber PLZ+Ort allein eindeutig auflösbar waren -
        # Bundesland/Gemeinde/Koordinaten stehen dann auf Ortsebene, nur
        # die Straße selbst ist im Kartendienst nicht erfasst. Gelb statt
        # Rot: Sales weiß, woran es liegt (Kartendatenlücke, keine
        # Falscheingabe), und hat trotzdem ein Bundesland zum Einordnen.
        return AmpelResult("gelb", "Ort bestätigt, Straße nicht in der Karte gefunden")

    if geocode_status == "fehlgeschlagen":
        return AmpelResult("grau", "Geocoding ausstehend (Dienst nicht erreichbar)")

    if geocode_status == "offen":
        return AmpelResult("grau", "Prüfung läuft")

    if geocode_status == "entfaellt":
        return AmpelResult("grau", "Geocoding entfällt (durch Korrektur ersetzt)")

    if geocode_status == "simuliert":
        return AmpelResult("grau", "Geocoding simuliert (Testmodus, keine echte Prüfung)")

    if geocode_status == "mehrdeutig":
        if geocode_candidate_count:
            return AmpelResult(
                "gelb",
                f"Adresse mehrdeutig: {geocode_candidate_count} mögliche Orte — im Gespräch klären",
            )
        return AmpelResult("gelb", "Adresse mehrdeutig — im Gespräch klären")

    if geocode_status != "ok":
        raise ValueError(f"ampel: unbekannter geocode_status {geocode_status!r}")

    if not phone_raw:
        return AmpelResult("gelb", "Nur per E-Mail erreichbar")

    if not phone_valid:
        return AmpelResult("gelb", f"Telefonnummer nicht lesbar: {phone_raw}")

    if not postal_code:
        return AmpelResult("gelb", "Keine PLZ angegeben — Ort per Geocoding bestätigt")

    return AmpelResult("gruen", "Vollständig")
