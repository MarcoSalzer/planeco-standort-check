import logging
import os
import pathlib
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.channel import HEARD_ABOUT_OPTIONS, derive_channel
from app.core.content_hash import content_hash
from app.core.normalize import normalize_email, normalize_name, normalize_phone
from app.core.spam import detect_spam
from app.core.validation import validate_submission
from app.db import get_connection
from app.submission import NewLeadData, persist_submission

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI()

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_VALUE_FIELDS = (
    "street", "postal_code", "city", "email", "phone", "name", "is_owner",
    "contact_time_preference", "heard_about", "message",
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "referrer", "landing_page",
)


def _empty_values() -> dict[str, str]:
    return {field: "" for field in _VALUE_FIELDS}


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
    values = _empty_values()
    values.update(
        utm_source=request.query_params.get("utm_source") or "",
        utm_medium=request.query_params.get("utm_medium") or "",
        utm_campaign=request.query_params.get("utm_campaign") or "",
        utm_term=request.query_params.get("utm_term") or "",
        utm_content=request.query_params.get("utm_content") or "",
        gclid=request.query_params.get("gclid") or "",
        fbclid=request.query_params.get("fbclid") or "",
        referrer=request.headers.get("referer") or "",
        landing_page=str(request.url),
    )
    context = {
        "values": values,
        "errors": {},
        "submission_token": str(uuid.uuid4()),
        "form_rendered_at": datetime.now(timezone.utc).isoformat(),
        "heard_about_options": HEARD_ABOUT_OPTIONS,
        "kontakt_email": os.environ.get("KONTAKT_EMAIL") or None,
        "kontakt_telefon": os.environ.get("KONTAKT_TELEFON") or None,
    }
    return templates.TemplateResponse(request=request, name="form.html", context=context)


@app.get("/datenschutz")
def datenschutz(request: Request):
    context = {"kontakt_email": os.environ.get("KONTAKT_EMAIL") or None}
    return templates.TemplateResponse(request=request, name="datenschutz.html", context=context)


@app.get("/danke")
def danke(request: Request):
    return templates.TemplateResponse(request=request, name="danke.html", context={})


def _parse_is_owner(raw: str | None) -> bool | None:
    if raw == "ja":
        return True
    if raw == "nein":
        return False
    return None


@app.post("/submit")
async def submit(request: Request):
    submitted_at = datetime.now(timezone.utc)
    form_data = await request.form()

    def field(name: str) -> str | None:
        value = form_data.get(name)
        return value.strip() if isinstance(value, str) else None

    street = field("street")
    postal_code = field("postal_code") or None
    city = field("city")
    email = field("email")
    phone_raw = field("phone") or None
    name_raw = field("name") or None
    is_owner_raw = form_data.get("is_owner")
    is_owner = _parse_is_owner(is_owner_raw if isinstance(is_owner_raw, str) else None)
    contact_time_preference = field("contact_time_preference") or None
    heard_about = field("heard_about") or None
    message = field("message") or None
    privacy_accepted = form_data.get("privacy_accepted") == "on"

    honeypot_raw = form_data.get("website")
    honeypot_value = honeypot_raw if isinstance(honeypot_raw, str) else None

    form_rendered_at_raw = form_data.get("form_rendered_at")
    elapsed_seconds = None
    if isinstance(form_rendered_at_raw, str):
        try:
            rendered_at = datetime.fromisoformat(form_rendered_at_raw)
            elapsed_seconds = (submitted_at - rendered_at).total_seconds()
        except ValueError:
            elapsed_seconds = None

    values = _empty_values()
    values.update(
        street=street or "",
        postal_code=postal_code or "",
        city=city or "",
        email=email or "",
        phone=phone_raw or "",
        name=name_raw or "",
        is_owner=is_owner_raw if isinstance(is_owner_raw, str) else "",
        contact_time_preference=contact_time_preference or "",
        heard_about=heard_about or "",
        message=message or "",
        utm_source=field("utm_source") or "",
        utm_medium=field("utm_medium") or "",
        utm_campaign=field("utm_campaign") or "",
        utm_term=field("utm_term") or "",
        utm_content=field("utm_content") or "",
        gclid=field("gclid") or "",
        fbclid=field("fbclid") or "",
        referrer=field("referrer") or "",
        landing_page=field("landing_page") or "",
    )
    values["privacy_accepted"] = privacy_accepted

    errors = validate_submission(
        street=street,
        city=city,
        email=email,
        postal_code=postal_code,
        contact_time_preference=contact_time_preference,
        privacy_accepted=privacy_accepted,
    )
    if errors:
        context = {
            "values": values,
            "errors": errors,
            "submission_token": str(uuid.uuid4()),
            "form_rendered_at": datetime.now(timezone.utc).isoformat(),
            "heard_about_options": HEARD_ABOUT_OPTIONS,
            "kontakt_email": os.environ.get("KONTAKT_EMAIL") or None,
            "kontakt_telefon": os.environ.get("KONTAKT_TELEFON") or None,
        }
        return templates.TemplateResponse(
            request=request, name="form.html", context=context, status_code=422
        )

    is_spam, spam_reason = detect_spam(
        honeypot_value=honeypot_value, elapsed_seconds=elapsed_seconds, message=message
    )

    phone_e164, phone_valid = normalize_phone(phone_raw)
    email_normalized = normalize_email(email)
    name, name_normalized = normalize_name(name_raw)

    channel, channel_source = derive_channel(
        utm_source=field("utm_source"),
        gclid=field("gclid"),
        fbclid=field("fbclid"),
        referrer=field("referrer"),
        heard_about=heard_about,
    )

    lead_content_hash = content_hash(
        name=name,
        email_normalized=email_normalized,
        phone_e164=phone_e164,
        street=street,
        postal_code=postal_code,
        city=city,
        is_owner=is_owner,
        contact_time_preference=contact_time_preference,
        message=message,
        heard_about=heard_about,
    )

    submission_token_raw = form_data.get("submission_token")
    submission_token = (
        submission_token_raw if isinstance(submission_token_raw, str) and submission_token_raw else str(uuid.uuid4())
    )

    data = NewLeadData(
        submission_token=submission_token,
        name=name,
        name_raw=name_raw,
        name_normalized=name_normalized,
        email=email,
        email_normalized=email_normalized,
        phone_raw=phone_raw,
        phone_e164=phone_e164,
        phone_valid=phone_valid,
        street=street,
        postal_code=postal_code,
        city=city,
        is_owner=is_owner,
        contact_time_preference=contact_time_preference,
        message=message,
        heard_about=heard_about,
        utm_source=field("utm_source"),
        utm_medium=field("utm_medium"),
        utm_campaign=field("utm_campaign"),
        utm_term=field("utm_term"),
        utm_content=field("utm_content"),
        gclid=field("gclid"),
        fbclid=field("fbclid"),
        referrer=field("referrer"),
        landing_page=field("landing_page"),
        channel=channel,
        channel_source=channel_source,
        content_hash=lead_content_hash,
        is_spam=is_spam,
        spam_reason=spam_reason,
        privacy_accepted_at=submitted_at,
    )

    with get_connection() as conn:
        persist_submission(conn, data)

    return RedirectResponse(url="/danke", status_code=303)
