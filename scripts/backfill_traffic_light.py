"""Einmaliger Backfill für Phase 4 Block c: traffic_light/traffic_light_reason
für Bestandszeilen nachrechnen, die vor der Umstellung auf "bei jedem
Schreibvorgang berechnen" entstanden sind (Marco, 2026-08-17).

Rechnet nebenbei geocode_candidate_count für bestehende mehrdeutig-Zeilen
aus dem bereits gespeicherten geocode_raw nach (rein, kein neuer
Nominatim-Aufruf) - candidate_count stand bisher nur im lead_events-
Payload, nie in einer eigenen Spalte. COALESCE lässt einen schon
gesetzten Wert unangetastet (z.B. wenn dieses Skript ein zweites Mal
läuft, nachdem einzelne Leads schon über den neuen Schreibpfad liefen).

Aufruf: PYTHONPATH=. .venv/bin/python scripts/backfill_traffic_light.py
        [--apply]   (ohne --apply nur Vorschau, keine Schreibvorgänge)
"""
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from psycopg.rows import dict_row  # noqa: E402

from app.core.ampel import ampel  # noqa: E402
from app.core.geocoding import parse_nominatim_results  # noqa: E402
from app.db import get_connection  # noqa: E402


def _recompute_candidate_count(geocode_status: str, geocode_raw, postal_code: str | None, city: str) -> int | None:
    if geocode_status != "mehrdeutig" or not geocode_raw or not geocode_raw.get("results"):
        return None
    # expected_postal_code/expected_city seit dem Adress-Abgleich-Fund
    # (2026-08-18, s. docs/FUNDE.md) Pflichtparameter - hier dieselbe
    # PLZ/Ort-Spalte wie beim ursprünglichen geocode()-Aufruf, damit die
    # Nachberechnung exakt dieselbe Klassifikation reproduziert.
    return parse_nominatim_results(
        geocode_raw["results"], expected_postal_code=postal_code, expected_city=city
    ).candidate_count


def main() -> None:
    apply = "--apply" in sys.argv

    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, is_spam, spam_reason, in_service_area, geocode_status, geo_state,
                   geo_country, geo_postal_code, geocode_candidate_count, geocode_raw, phone_raw, phone_valid, postal_code, city
            FROM leads
            """
        )
        rows = cur.fetchall()

    print(f"{len(rows)} Leads gefunden.")

    updates = []
    for row in rows:
        candidate_count = row["geocode_candidate_count"]
        if candidate_count is None:
            candidate_count = _recompute_candidate_count(
                row["geocode_status"], row["geocode_raw"], row["postal_code"], row["city"]
            )
        result = ampel(
            is_spam=row["is_spam"],
            spam_reason=row["spam_reason"],
            in_service_area=row["in_service_area"],
            geocode_status=row["geocode_status"],
            geo_state=row["geo_state"],
            geo_country=row["geo_country"],
            geo_postal_code=row["geo_postal_code"],
            geocode_candidate_count=candidate_count,
            phone_raw=row["phone_raw"],
            phone_valid=row["phone_valid"],
            postal_code=row["postal_code"],
        )
        updates.append((str(row["id"]), result.farbe, result.grund, candidate_count))

    verteilung = Counter(u[1] for u in updates)
    print("Ampel-Verteilung (Vorschau):", dict(verteilung))
    nachgerechnete_kandidaten = sum(
        1 for row, u in zip(rows, updates) if row["geocode_candidate_count"] is None and u[3] is not None
    )
    print(f"geocode_candidate_count neu ermittelt (aus gespeichertem geocode_raw): {nachgerechnete_kandidaten}")

    if not apply:
        print("\nNur Vorschau (kein --apply). Nichts geschrieben.")
        return

    with get_connection() as conn:
        for lead_id, farbe, grund, candidate_count in updates:
            conn.execute(
                """
                UPDATE leads
                SET traffic_light = %(farbe)s, traffic_light_reason = %(grund)s,
                    geocode_candidate_count = COALESCE(geocode_candidate_count, %(candidate_count)s)
                WHERE id = %(id)s
                """,
                {"farbe": farbe, "grund": grund, "candidate_count": candidate_count, "id": lead_id},
            )

    with get_connection() as conn:
        fehlend = conn.execute("SELECT count(*) FROM leads WHERE traffic_light IS NULL").fetchone()[0]
        gesamt = conn.execute("SELECT count(*) FROM leads").fetchone()[0]
    print(f"\nFertig: {gesamt - fehlend}/{gesamt} Zeilen mit traffic_light versehen, {fehlend} ohne (sollte 0 sein).")


if __name__ == "__main__":
    main()
