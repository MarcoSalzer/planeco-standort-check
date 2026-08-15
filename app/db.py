import os

import psycopg


def get_connection() -> psycopg.Connection:
    """Öffnet eine neue DB-Connection für einen einzelnen Request.

    Kein globaler Pool im Modulzustand (Serverless-Instanzen werden ohne
    Vorwarnung beendet). prepare_threshold=None, weil der Supabase
    Transaction Pooler (Port 6543) keine Prepared Statements unterstützt.
    """
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL ist nicht gesetzt.")
    return psycopg.connect(dsn, prepare_threshold=None)
