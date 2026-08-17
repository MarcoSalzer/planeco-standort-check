"""Schreibt traffic_light/traffic_light_reason (Konzept §B/§F, Phase 4
Block c) - IMMER direkt nach jeder Änderung an einer ampel-relevanten
Spalte aufrufen: Submit (app/submission.py::_insert_lead), F3-Korrektur
am Vorgänger (_supersede), Geocoding-Ergebnis (app/retry.py), manueller
Statuswechsel/Spam-Freigabe (app/admin.py::update_lead_bearbeitung).

Ein Schreibpfad, der das vergisst, wäre wieder das bekannte "vergessene
Stelle"-Muster (Marco, 2026-08-17, nach dem geocode_status='simuliert'-
Fund) - deshalb ein einziger, immer gleicher Aufruf statt die
ampel()-relevanten Felder an jeder Stelle einzeln durchzureichen. Kostet
einen zusätzlichen Read pro Schreibvorgang; bei diesem Datenvolumen
irrelevant, und die Konsistenz-Garantie ("ein Aufruf, immer derselbe
Weg") wiegt schwerer als die kleine Ersparnis, die Felder stattdessen von
Aufrufer zu Aufrufer durchzureichen.

app.core.ampel bleibt eine reine Funktion (CLAUDE.md Regel 5); dieses
Modul ist die einzige Stelle, die sie mit einem frischen DB-Read/Write
verbindet.
"""
import psycopg

from app.core.ampel import AmpelResult, ampel


def apply_traffic_light(conn: psycopg.Connection, lead_id: str) -> AmpelResult:
    row = conn.execute(
        """
        SELECT is_spam, spam_reason, in_service_area, geocode_status, geo_state,
               geo_country, geo_postal_code, geocode_candidate_count, phone_raw, phone_valid, postal_code
        FROM leads WHERE id = %(id)s
        """,
        {"id": lead_id},
    ).fetchone()
    result = ampel(
        is_spam=row[0],
        spam_reason=row[1],
        in_service_area=row[2],
        geocode_status=row[3],
        geo_state=row[4],
        geo_country=row[5],
        geo_postal_code=row[6],
        geocode_candidate_count=row[7],
        phone_raw=row[8],
        phone_valid=row[9],
        postal_code=row[10],
    )
    conn.execute(
        "UPDATE leads SET traffic_light = %(farbe)s, traffic_light_reason = %(grund)s WHERE id = %(id)s",
        {"farbe": result.farbe, "grund": result.grund, "id": lead_id},
    )
    return result
