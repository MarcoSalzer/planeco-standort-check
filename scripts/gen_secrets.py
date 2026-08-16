#!/usr/bin/env python3
"""Erzeugt ADMIN_PASSWORD_HASH, SESSION_SECRET, RETRY_SECRET und
EDIT_TOKEN_SECRET zum Eintragen in .env.

Vier getrennte Secrets für vier Sicherheitsdomänen: SESSION_SECRET schützt
den Admin-Login, RETRY_SECRET den Cron-Retry-Endpunkt, EDIT_TOKEN_SECRET die
Korrektur-Links, die an jeden Interessenten per Mail rausgehen und daher
unabhängig rotierbar sein müssen, ohne Admin-Sessions oder den Retry-Zugang
zu invalidieren.
"""
import getpass
import secrets

import bcrypt


def main() -> None:
    password = getpass.getpass("Admin-Passwort: ")
    confirm = getpass.getpass("Admin-Passwort (wiederholen): ")
    if password != confirm:
        raise SystemExit("Passwörter stimmen nicht überein.")
    if not password:
        raise SystemExit("Passwort darf nicht leer sein.")

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    session_secret = secrets.token_urlsafe(32)
    retry_secret = secrets.token_urlsafe(32)
    edit_token_secret = secrets.token_urlsafe(32)

    print()
    print("In .env eintragen:")
    print(f"ADMIN_PASSWORD_HASH={password_hash}")
    print(f"SESSION_SECRET={session_secret}")
    print(f"RETRY_SECRET={retry_secret}")
    print(f"EDIT_TOKEN_SECRET={edit_token_secret}")


if __name__ == "__main__":
    main()
