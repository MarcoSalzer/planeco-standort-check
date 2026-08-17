"""Verifiziert, dass Python-Code jeden in der Datenbank per CHECK-Constraint
erlaubten Statuswert verarbeitet - die Constraint ist die Wahrheit, keine von
Hand gepflegte Kopie davon (Marco, 2026-08-17, Fund s. docs/FUNDE.md):
geocode_status='simuliert' wurde per Migration erlaubt, aber in
app.core.ampel.ampel() vergessen - ein einziger Lead in diesem Zustand
brachte die komplette Lead-Liste zum Absturz, weil ampel() bei einem
unbekannten Wert bewusst wirft statt zu raten (CLAUDE.md Regel 3).

Bewusst NICHT unter tests/core/: braucht eine echte DB-Verbindung
(DATABASE_URL), um die aktuell gültige CHECK-Constraint zu lesen - anders
als jeder Test dort. app.core.ampel bleibt selbst eine reine, DB-freie
Funktion (CLAUDE.md Regel 5); nur DIESER Test braucht die DB als Quelle der
Wahrheit für die Werteliste - sonst könnte die Testliste selbst genauso
still veralten wie der Code, den sie eigentlich absichern soll.
"""
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.core.ampel import ampel  # noqa: E402
from app.core.display import status_label  # noqa: E402
from app.db import get_connection  # noqa: E402


def _allowed_check_values(column: str) -> list[str]:
    """Liest die CHECK-Constraint 'leads_<column>_check' aus der echten DB
    und extrahiert die erlaubten Werte aus der von Postgres gelieferten
    Form `check (col = ANY (ARRAY['a'::text, 'b'::text, ...]))`."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'leads'::regclass AND conname = %(name)s",
            {"name": f"leads_{column}_check"},
        )
        row = cur.fetchone()
    if row is None:
        raise AssertionError(
            f"Keine CHECK-Constraint 'leads_{column}_check' gefunden - "
            f"Testannahme verletzt (Tabelle/Constraint umbenannt?)."
        )
    values = re.findall(r"'([^']*)'::text", row[0])
    if not values:
        raise AssertionError(f"Keine Werte aus der Constraint 'leads_{column}_check' extrahiert: {row[0]!r}")
    return values


_GEOCODE_STATUS_WERTE = _allowed_check_values("geocode_status")
_STATUS_WERTE = _allowed_check_values("status")


@pytest.mark.parametrize("geocode_status", _GEOCODE_STATUS_WERTE)
def test_ampel_behandelt_jeden_erlaubten_geocode_status(geocode_status):
    # Darf nicht werfen: jeder von der DB erlaubte Wert muss zu einer Ampel
    # führen, sonst legt ein einzelner Lead in diesem Zustand die komplette
    # Liste lahm (genau der Fund vom 17.08. - ein Dry-Run-Lead mit
    # geocode_status='simuliert' brachte /admin zum Absturz).
    result = ampel(
        is_spam=False, spam_reason=None, in_service_area=None,
        geocode_status=geocode_status, geo_state=None, geo_country=None, geo_postal_code=None,
        geocode_candidate_count=None, phone_raw=None, phone_valid=False,
        postal_code=None,
    )
    assert result.farbe in ("gruen", "gelb", "rot", "grau", "schwarz")
    assert result.grund


@pytest.mark.parametrize("status", _STATUS_WERTE)
def test_status_label_kennt_jeden_erlaubten_lead_status(status):
    # ampel() nimmt den Workflow-Status (neu/kontaktiert/...) gar nicht als
    # Parameter entgegen - bewusst so, die Ampel beschreibt Datenqualität,
    # nicht Pipeline-Position (s. Konzept §B: kein Bezug auf `status` in der
    # Regeltabelle). Der wörtliche Wunsch "status von der Ampel-Funktion
    # behandelt" lässt sich deshalb nicht 1:1 bauen. Als nächstliegendes
    # Äquivalent prüft dieser Test stattdessen status_label() - die einzige
    # Stelle, die `status` in Anzeigetext übersetzt. status_label() wirft
    # bei einem unbekannten Wert nicht (fällt graceful auf den Rohwert
    # zurück), aber ein fehlender Eintrag wäre dieselbe Fundart wie der
    # ampel()-Absturz, nur mit milderer Folge (unschöner Rohwert statt
    # abstürzender Liste) - deshalb hier trotzdem hart geprüft.
    label = status_label(status)
    assert label != status, f"status_label() hat keinen Eintrag für {status!r} und zeigt nur den Rohwert an"
