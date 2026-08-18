"""E-Mail-Zustellbarkeitsprüfung (Konzept §D/§K): MX-Record-Check über
email-validator/dnspython. Nicht pur (DNS-Zugriff, wie app/geocoding.py) -
bewusst NICHT Teil von app/core/validation.py, deren Docstring das explizit
ausschließt, damit die dortige Syntaxprüfung ohne Netzwerk testbar bleibt.

Läuft synchron im Submit-Pfad, weil eine bestätigt nicht zustellbare Domain
den Submit ablehnen soll (422, wie die übrigen Pflichtfeld-/Formatfehler) -
anders als Mail/Geocoding also KEINE Nebenwirkung nach dem INSERT, sondern
Teil der Ablehnung-oder-Annahme-Entscheidung davor. Trotzdem gilt CLAUDE.md
Regel 2 im Kern: ein ausgefallener DNS-Dienst (Timeout, kein Nameserver
erreichbar, oder ein unerwarteter Fehler außerhalb der von email_validator
selbst abgefangenen Fälle) darf nie einen Lead kosten - nur eine BESTÄTIGT
nicht zustellbare Domain (NXDOMAIN, kein MX/A/AAAA-Eintrag) lehnt ab.
"""
import logging

from email_validator import EmailNotValidError, validate_email

logger = logging.getLogger(__name__)

# Deutlich unter der 3s-Obergrenze aus CLAUDE.md Regel 2 - läuft synchron im
# Request, nicht als Best-effort-Nebenwirkung danach, muss also selbst dann
# eine akzeptable Antwortzeit behalten, wenn ein DNS-Server hängt statt
# sauber "kein Nameserver erreichbar" zurückzugeben.
MX_CHECK_TIMEOUT_SECONDS = 2


class EmailUndeliverable(Exception):
    """Domain bestätigt nicht zustellbar (NXDOMAIN, kein MX/A/AAAA-Eintrag,
    o.ä.) - der Aufrufer soll den Submit mit dieser Meldung ablehnen."""


def check_email_mx(email: str, *, dns_resolver: object | None = None) -> str:
    """Rückgabe 'geprueft' (MX/A/AAAA-Eintrag bestätigt gefunden) oder
    'nicht_pruefbar' (DNS-Prüfung selbst nicht möglich - Timeout, kein
    Nameserver erreichbar, oder ein unerwarteter Fehler). Wirft
    EmailUndeliverable NUR, wenn die Domain bestätigt keine Mail annehmen
    kann - das ist der einzige Fall, der den Submit ablehnen soll.

    dns_resolver: nur für Tests (Stub statt echtem Netzwerk-Resolver). Wird
    unverändert an email_validator durchgereicht - dessen eigene Regel
    verbietet, timeout UND dns_resolver gleichzeitig zu setzen (sonst
    ValueError), deshalb wird timeout nur ohne eigenen dns_resolver gesetzt.
    """
    kwargs: dict = {"check_deliverability": True}
    if dns_resolver is not None:
        kwargs["dns_resolver"] = dns_resolver
    else:
        kwargs["timeout"] = MX_CHECK_TIMEOUT_SECONDS

    try:
        result = validate_email(email, **kwargs)
    except EmailNotValidError as exc:
        # email_validator wirft das hier ausschließlich wegen der
        # Zustellbarkeit (Syntax wurde bereits vorher in
        # validate_submission() ohne DNS-Zugriff geprüft) - z.B. NXDOMAIN
        # oder kein MX/A/AAAA-Eintrag (s. deliverability.py der Bibliothek:
        # dns.resolver.NoNameservers und dns.exception.Timeout werfen dort
        # bewusst NICHT, sondern liefern "unknown-deliverability" zurück -
        # nur eine bestätigt nicht zustellbare Domain landet hier).
        raise EmailUndeliverable(str(exc)) from exc
    except Exception:
        # Alles andere - z.B. wenn schon die Resolver-Initialisierung selbst
        # scheitert (dns.resolver.get_default_resolver() läuft in
        # email_validator AUSSERHALB von dessen eigenem try/except) - darf
        # laut Marco keinen Lead kosten. Geloggt, damit ein wiederkehrender
        # DNS-Ausfall nicht unbemerkt bleibt, aber nicht geworfen.
        logger.warning("E-Mail-Zustellbarkeitsprüfung unerwartet fehlgeschlagen, Prüfung übersprungen", exc_info=True)
        return "nicht_pruefbar"

    # result.mx wird von email_validator NIE gesetzt (kein Attribut, kein
    # None-Default - direkter Zugriff wirft AttributeError), wenn intern
    # "unknown-deliverability" (Timeout/kein Nameserver) ermittelt wurde,
    # statt eine Exception zu werfen - deshalb getattr() mit Fallback statt
    # result.mx direkt.
    return "geprueft" if getattr(result, "mx", None) is not None else "nicht_pruefbar"
