"""Zentrale Stelle zum Lesen von Umgebungsvariablen.

Entfernt umschließenden Whitespace (Leerzeichen, Zeilenumbrüche) bei jedem
Lesevorgang - ein Copy&Paste-Fehler beim Setzen einer Env-Variable in einer
UI wie Vercel (z.B. ein Trailing-Newline aus der Zwischenablage) soll nicht
erst als kryptischer Fehler tief im Code auffallen (BREVO_API_KEY mit
Trailing-Newline -> "Illegal header value" beim Mailversand, s.
docs/FUNDE.md). Alle Module, die os.environ lesen, gehen über diese beiden
Funktionen statt os.environ direkt anzusprechen.
"""
import os


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip()


def require_env(name: str) -> str:
    value = get_env(name)
    if not value:
        raise RuntimeError(f"{name} ist nicht gesetzt.")
    return value
