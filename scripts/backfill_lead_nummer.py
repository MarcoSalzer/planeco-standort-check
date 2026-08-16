"""Einmaliger Backfill für migrations/0006_lead_nummer.sql: bestehende
Zeilen nachträglich durchnummerieren, in der Reihenfolge des Eingangs
(Marco, 2026-08-16).

Ein Vorgang kann sowohl eine Korrekturkette (superseded_by) als auch
Duplikate (duplicate_of) umfassen, und zwar gemischt: Lead A wird per F2
zu B dupliziert, dann A per F3 zu C korrigiert, dann C per F2 zu D
dupliziert - A/B/C/D gehören alle zum selben Vorgang, obwohl B nie mit C
oder D direkt verknüpft ist. Union-Find über BEIDE Kantentypen findet die
vollständigen Cluster; ohne das bekämen B und D fälschlich eigene
Nummern.

Nutzt dieselbe lead_nummer_seq wie der Live-Betrieb (app/submission.py),
damit künftige Nummern nahtlos anschließen statt zu kollidieren.

Aufruf: PYTHONPATH=. .venv/bin/python scripts/backfill_lead_nummer.py
        [--apply]   (ohne --apply nur Vorschau, keine Schreibvorgänge)
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from psycopg.rows import dict_row  # noqa: E402

from app.db import get_connection  # noqa: E402


def find(parent: dict, x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(parent: dict, a: str, b: str) -> None:
    ra, rb = find(parent, a), find(parent, b)
    if ra != rb:
        parent[ra] = rb


def compute_groups(rows: list[dict]) -> list[list[dict]]:
    parent = {str(r["id"]): str(r["id"]) for r in rows}
    by_id = {str(r["id"]): r for r in rows}

    for row in rows:
        rid = str(row["id"])
        if row["duplicate_of"]:
            union(parent, rid, str(row["duplicate_of"]))
        if row["superseded_by"]:
            union(parent, rid, str(row["superseded_by"]))

    clusters: dict[str, list[dict]] = {}
    for rid in by_id:
        root = find(parent, rid)
        clusters.setdefault(root, []).append(by_id[rid])

    groups = list(clusters.values())
    groups.sort(key=lambda g: min(r["created_at"] for r in g))
    return groups


def main() -> None:
    apply = "--apply" in sys.argv

    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, created_at, duplicate_of, superseded_by, lead_nummer FROM leads ORDER BY created_at")
        rows = cur.fetchall()

    already_numbered = [r for r in rows if r["lead_nummer"] is not None]
    if already_numbered:
        print(f"ABBRUCH: {len(already_numbered)} Zeilen haben bereits eine lead_nummer - "
              f"Backfill ist nur für den Erststart gedacht, nicht für einen Re-Run.")
        sys.exit(1)

    groups = compute_groups(rows)
    print(f"{len(rows)} Leads in {len(groups)} Vorgänge gruppiert (per Union-Find über "
          f"duplicate_of + superseded_by).\n")

    multi = [g for g in groups if len(g) > 1]
    print(f"Vorschau ({len(multi)} Vorgänge mit mehr als einer Zeile, der Rest ist je 1 Zeile):")
    for i, group in enumerate(groups, start=1):
        if len(group) > 1:
            ids = [str(r["id"])[:8] for r in sorted(group, key=lambda r: r["created_at"])]
            print(f"  Vorgang #{i}: {len(group)} Zeilen -> {ids}")

    if not apply:
        print("\nNur Vorschau (kein --apply). Nichts geschrieben.")
        return

    with get_connection() as conn:
        for i, group in enumerate(groups, start=1):
            nummer = conn.execute("SELECT nextval('lead_nummer_seq')").fetchone()[0]
            ids = [str(r["id"]) for r in group]
            conn.execute(
                "UPDATE leads SET lead_nummer = %(nummer)s WHERE id = ANY(%(ids)s)",
                {"nummer": nummer, "ids": ids},
            )
            if i != nummer:
                print(f"HINWEIS: Vorgang #{i} bekam Sequenzwert {nummer} (Sequenz war nicht bei 1) - unproblematisch.")

    with get_connection() as conn:
        unnumbered = conn.execute("SELECT count(*) FROM leads WHERE lead_nummer IS NULL").fetchone()[0]
        total = conn.execute("SELECT count(*) FROM leads").fetchone()[0]
    print(f"\nFertig: {total - unnumbered}/{total} Zeilen nummeriert, {unnumbered} ohne Nummer (sollte 0 sein).")


if __name__ == "__main__":
    main()
