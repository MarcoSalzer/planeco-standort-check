import logging
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

# Muss vor jedem app.*-Import laufen, der transitiv app.config importiert
# (app.mail -> app.config liest MAX_EMAILS_PER_DAY etc. beim Modul-Import
# sofort aus os.environ - ohne load_dotenv() vorher schlägt der Import fehl,
# selbst wenn .env die Werte enthält).
load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402

from app.admin import router as admin_router  # noqa: E402
from app.core.channel import HEARD_ABOUT_OPTIONS, derive_channel  # noqa: E402
from app.core.content_hash import content_hash  # noqa: E402
from app.core.dedup import DedupCase  # noqa: E402
from app.core.edit_token import generate_edit_token, verify_edit_token  # noqa: E402
from app.core.normalize import (  # noqa: E402
    normalize_email,
    normalize_heard_about,
    normalize_name,
    normalize_phone,
)
from app.core.spam import detect_spam  # noqa: E402
from app.core.validation import validate_submission  # noqa: E402
from app.db import get_connection  # noqa: E402
from app.env import get_env  # noqa: E402
from app.mail import send_confirmation_email  # noqa: E402
from app.submission import NewLeadData, persist_submission, resolve_current_lead  # noqa: E402
from app.templating import templates  # noqa: E402

# Ohne das bleibt der Root-Logger auf WARNING (Python-Default) und
# DRY_RUN_EMAIL-Log-Ausgaben (app.mail.dry_run, Level INFO) verschwinden
# spurlos - genau die Ausgabe, die zur Prüfung eines Dry-Runs gedacht ist.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

logger = logging.getLogger(__name__)

app = FastAPI()
app.include_router(admin_router)

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


def _is_owner_to_form_value(is_owner: bool | None) -> str:
    if is_owner is True:
        return "ja"
    if is_owner is False:
        return "nein"
    return ""


@app.get("/")
def form(request: Request):
    values = _empty_values()
    is_edit_mode = False

    edit_token = request.query_params.get("k")
    if edit_token:
        secret = get_env("EDIT_TOKEN_SECRET")
        lead_id = verify_edit_token(edit_token, secret) if secret else None
        if secret is None:
            logger.warning("EDIT_TOKEN_SECRET nicht gesetzt - Korrektur-Link kann nicht geprüft werden")
        if lead_id:
            with get_connection() as conn:
                current = resolve_current_lead(conn, lead_id)
            if current:
                is_edit_mode = True
                values.update(
                    street=current["street"] or "",
                    postal_code=current["postal_code"] or "",
                    city=current["city"] or "",
                    email=current["email"] or "",
                    phone=current["phone_raw"] or "",
                    name=current["name_raw"] or "",
                    is_owner=_is_owner_to_form_value(current["is_owner"]),
                    contact_time_preference=current["contact_time_preference"] or "",
                    heard_about=current["heard_about"] or "",
                    message=current["message"] or "",
                )
                # expansion_opt_in ist wie privacy_accepted ein Checkbox-Feld,
                # kein Text - separat gesetzt statt über _VALUE_FIELDS/
                # _empty_values() (dieselbe Behandlung wie privacy_accepted
                # unten), damit ein vorheriges "Bitte informieren Sie mich
                # über neue Regionen" beim Korrigieren erhalten bleibt statt
                # beim erneuten Absenden stillschweigend zu verschwinden.
                values["expansion_opt_in"] = bool(current["expansion_opt_in"])

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
        "is_edit_mode": is_edit_mode,
        "submission_token": str(uuid.uuid4()),
        "form_rendered_at": datetime.now(timezone.utc).isoformat(),
        "heard_about_options": HEARD_ABOUT_OPTIONS,
        "kontakt_email": get_env("KONTAKT_EMAIL") or None,
        "kontakt_telefon": get_env("KONTAKT_TELEFON") or None,
    }
    return templates.TemplateResponse(request=request, name="form.html", context=context)


@app.get("/datenschutz")
def datenschutz(request: Request):
    context = {"kontakt_email": get_env("KONTAKT_EMAIL") or None}
    return templates.TemplateResponse(request=request, name="datenschutz.html", context=context)


@app.get("/danke")
def danke(request: Request):
    token = request.query_params.get("k")
    edit_url = f"/?k={token}" if token else None
    return templates.TemplateResponse(request=request, name="danke.html", context={"edit_url": edit_url})


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
    expansion_opt_in = form_data.get("expansion_opt_in") == "on"

    honeypot_raw = form_data.get("website")
    honeypot_value = honeypot_raw if isinstance(honeypot_raw, str) else None
    is_edit_mode = form_data.get("is_edit_mode") == "1"

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
    values["expansion_opt_in"] = expansion_opt_in

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
            "is_edit_mode": is_edit_mode,
            "submission_token": str(uuid.uuid4()),
            "form_rendered_at": datetime.now(timezone.utc).isoformat(),
            "heard_about_options": HEARD_ABOUT_OPTIONS,
            "kontakt_email": get_env("KONTAKT_EMAIL") or None,
            "kontakt_telefon": get_env("KONTAKT_TELEFON") or None,
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
    # Unbekannter Wert -> "keine Angabe" statt Ablehnung (anders als
    # contact_time_preference): heard_about ist Selbstauskunft, kein
    # Pflichtfeld mit Auswirkung auf Mailtext o.ä. - ein 422 dafür wäre
    # unverhältnismäßig. Der Rohwert geht trotzdem nicht verloren (CLAUDE.md
    # Regel 4), s. unexpected_fields/Event 'unerwarteter_feldwert' unten.
    heard_about_normalized, heard_about_unerwartet = normalize_heard_about(heard_about)

    # Attributionsfelder: leerer String -> None, analog zu heard_about/
    # phone/name oben. Die Hidden Fields im Formular senden bei fehlendem
    # UTM-Parameter value="" statt gar keinen Wert - ohne diese
    # Normalisierung landen '' und NULL als zwei verschiedene Gruppen in
    # jeder Auswertung, die nach diesen Spalten gruppiert (Fund beim Bauen
    # des Auswertungs-Tabs, s. docs/FUNDE.md).
    utm_source = field("utm_source") or None
    utm_medium = field("utm_medium") or None
    utm_campaign = field("utm_campaign") or None
    utm_term = field("utm_term") or None
    utm_content = field("utm_content") or None
    gclid = field("gclid") or None
    fbclid = field("fbclid") or None
    referrer = field("referrer") or None
    landing_page = field("landing_page") or None

    channel, channel_source = derive_channel(
        utm_source=utm_source,
        gclid=gclid,
        fbclid=fbclid,
        referrer=referrer,
        heard_about=heard_about_normalized,
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
        heard_about=heard_about_normalized,
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
        heard_about=heard_about_normalized,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        utm_term=utm_term,
        utm_content=utm_content,
        gclid=gclid,
        fbclid=fbclid,
        referrer=referrer,
        landing_page=landing_page,
        channel=channel,
        channel_source=channel_source,
        content_hash=lead_content_hash,
        is_spam=is_spam,
        spam_reason=spam_reason,
        privacy_accepted_at=submitted_at,
        expansion_opt_in=expansion_opt_in,
    )

    unexpected_fields = {"heard_about": heard_about} if heard_about_unerwartet else {}

    with get_connection() as conn:
        result = persist_submission(conn, data, unexpected_fields=unexpected_fields)

    if result.case != DedupCase.F1_TECHNISCHE_DOPPLUNG:
        try:
            with get_connection() as conn:
                send_confirmation_email(
                    conn, result.lead_id, result.final_data, str(request.base_url), result.case
                )
        except Exception:
            # Nebenwirkung darf den Submit nie zum Scheitern bringen (CLAUDE.md
            # Regel 2). send_confirmation_email fängt Brevo-/Netzwerkfehler
            # bereits selbst ab - dieser Fang ist nur das zusätzliche Netz für
            # alles andere (z.B. ein DB-Fehler beim Status-Update selbst).
            logger.exception("Bestätigungsmail-Schritt fehlgeschlagen für Lead %s", result.lead_id)

    secret = get_env("EDIT_TOKEN_SECRET")
    danke_url = "/danke"
    if secret:
        danke_url = f"/danke?k={generate_edit_token(result.lead_id, secret)}"
    else:
        logger.warning("EDIT_TOKEN_SECRET nicht gesetzt - Danke-Seite ohne Korrektur-Link")

    return RedirectResponse(url=danke_url, status_code=303)
