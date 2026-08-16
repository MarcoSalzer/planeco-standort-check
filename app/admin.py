"""Admin-Dashboard: Login jetzt, Lead-Übersicht folgt (Konzept §6).

Session per signiertem Cookie (itsdangerous, SESSION_SECRET - eigenes
Secret, getrennt von EDIT_TOKEN_SECRET, s. app/core/admin_auth.py).
"""
import logging
import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.core.admin_auth import (
    SESSION_MAX_AGE_SECONDS,
    generate_session_token,
    verify_credentials,
    verify_session_token,
)
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")

SESSION_COOKIE_NAME = "standort_check_admin_session"


def _current_admin(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        logger.warning("SESSION_SECRET nicht gesetzt - Admin-Session kann nicht geprüft werden")
        return None
    return verify_session_token(token, secret)


@router.get("/login")
def login_form(request: Request):
    if _current_admin(request):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(request=request, name="admin_login.html", context={"error": None})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    admin_user = os.environ.get("ADMIN_USER")
    admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    session_secret = os.environ.get("SESSION_SECRET")

    if not admin_user or not admin_password_hash or not session_secret:
        logger.warning("ADMIN_USER/ADMIN_PASSWORD_HASH/SESSION_SECRET nicht vollständig gesetzt")
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={"error": "Login ist derzeit nicht konfiguriert."},
            status_code=503,
        )

    ok = verify_credentials(
        username, password, expected_username=admin_user, expected_password_hash=admin_password_hash
    )
    if not ok:
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={"error": "Benutzername oder Passwort falsch."},
            status_code=401,
        )

    token = generate_session_token(username, session_secret)
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.get("")
def dashboard(request: Request):
    admin_username = _current_admin(request)
    if not admin_username:
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse(
        request=request, name="admin_dashboard.html", context={"username": admin_username}
    )
