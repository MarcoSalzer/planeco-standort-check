"""Tests für app/email_check.py mit einem injizierten DNS-Resolver-Stub -
kein echtes Netzwerk nötig. Die eigentliche DNS-Logik (dns.resolver/
dns.exception) kommt aus email-validator/dnspython und wird hier nicht neu
getestet, nur die Interpretation ihrer Ergebnisse durch check_email_mx()."""
import dns.exception
import dns.resolver
import pytest

from app.email_check import EmailUndeliverable, check_email_mx


class _MX:
    def __init__(self, exchange: str, preference: int = 10):
        self.exchange = exchange
        self.preference = preference


class _StubResolver:
    """Simuliert dns.resolver.Resolver.resolve() für einen einzelnen
    Domainnamen - lifetime wird nur gesetzt, nie gelesen (email_validator
    setzt es bei eigenem dns_resolver nicht, s. app/email_check.py)."""

    def __init__(self, antworten: dict):
        self.antworten = antworten
        self.lifetime = None

    def resolve(self, domain, rdtype):
        ergebnis = self.antworten.get(rdtype)
        if isinstance(ergebnis, Exception):
            raise ergebnis
        if ergebnis is None:
            raise dns.resolver.NoAnswer()
        return ergebnis


def test_mx_gefunden_ergibt_geprueft():
    resolver = _StubResolver({"MX": [_MX("mail.example.com.")]})
    assert check_email_mx("tom@example.com", dns_resolver=resolver) == "geprueft"


def test_nxdomain_wirft_email_undeliverable():
    resolver = _StubResolver({"MX": dns.resolver.NXDOMAIN()})
    with pytest.raises(EmailUndeliverable):
        check_email_mx("tom@gmial.com", dns_resolver=resolver)


def test_kein_mx_a_aaaa_wirft_email_undeliverable():
    resolver = _StubResolver({"MX": None, "A": None, "AAAA": None})
    with pytest.raises(EmailUndeliverable):
        check_email_mx("tom@example.com", dns_resolver=resolver)


def test_dns_timeout_ergibt_nicht_pruefbar_statt_ablehnung():
    resolver = _StubResolver({"MX": dns.exception.Timeout()})
    assert check_email_mx("tom@example.com", dns_resolver=resolver) == "nicht_pruefbar"


def test_kein_nameserver_erreichbar_ergibt_nicht_pruefbar_statt_ablehnung():
    resolver = _StubResolver({"MX": dns.resolver.NoNameservers()})
    assert check_email_mx("tom@example.com", dns_resolver=resolver) == "nicht_pruefbar"


def test_unerwarteter_fehler_im_resolver_fuehrt_zu_ablehnung():
    # email_validator selbst fängt nur die oben getesteten, bekannten
    # DNS-Fehlertypen permissiv ab - alles andere wird von der Bibliothek
    # als EmailUndeliverableError gewertet (s. deliverability.py). Bewusst
    # dokumentiert, kein Wunschverhalten: nur Timeout/NoNameservers sind
    # als "DNS-Dienst nicht erreichbar" abgesichert, wie von Marco verlangt.
    resolver = _StubResolver({"MX": RuntimeError("unerwartet")})
    with pytest.raises(EmailUndeliverable):
        check_email_mx("tom@example.com", dns_resolver=resolver)
