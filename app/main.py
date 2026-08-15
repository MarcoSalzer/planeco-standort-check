import logging
import os
import pathlib
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.channel import HEARD_ABOUT_OPTIONS
from app.db import get_connection

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI()

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/health")
def health() -> JSONResponse:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        logger.exception("Health-Check: Datenbankabfrage fehlgeschlagen")
        return JSONResponse(status_code=503, content={"status": "error", "db": False})
    return JSONResponse(content={"status": "ok", "db": True})


@app.get("/")
def form(request: Request):
    context = {
        "utm_source": request.query_params.get("utm_source"),
        "utm_medium": request.query_params.get("utm_medium"),
        "utm_campaign": request.query_params.get("utm_campaign"),
        "utm_term": request.query_params.get("utm_term"),
        "utm_content": request.query_params.get("utm_content"),
        "gclid": request.query_params.get("gclid"),
        "fbclid": request.query_params.get("fbclid"),
        "referrer": request.headers.get("referer"),
        "landing_page": str(request.url),
        "submission_token": str(uuid.uuid4()),
        "form_rendered_at": datetime.now(timezone.utc).isoformat(),
        "heard_about_options": HEARD_ABOUT_OPTIONS,
        "kontakt_email": os.environ.get("KONTAKT_EMAIL") or None,
        "kontakt_telefon": os.environ.get("KONTAKT_TELEFON") or None,
    }
    return templates.TemplateResponse(request=request, name="form.html", context=context)
