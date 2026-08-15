import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.db import get_connection

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/health")
def health() -> JSONResponse:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        logger.exception("Health-Check: Datenbankabfrage fehlgeschlagen")
        return JSONResponse(status_code=503, content={"status": "error", "db": False})
    return JSONResponse(content={"status": "ok", "db": True})
