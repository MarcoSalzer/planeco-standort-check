"""dedup_decision: Duplikat-/Korrektur-Entscheidung F1-F4 (Konzept §4).

Reine Entscheidungslogik. Die eigentliche Suche nach einem passenden
Bestandslead (per phone_e164/email_normalized/Adresse) läuft als
DB-Abfrage außerhalb dieser Funktion; hier kommt nur das Ergebnis
("candidate") rein. F1 (identischer submission_token) wird ebenfalls
extern per DB-Unique-Constraint geprüft und als Flag hereingereicht,
damit alle vier Fälle in einer einzigen, testbaren Funktion landen.

Reihenfolge, erste zutreffende Regel gewinnt:
F1 (Token-Replay) > F2 (identischer Inhalt) > F3 (Adresse matcht,
Inhalt weicht ab) > F4 (nur Person matcht) > NEU.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.core.text import canonical_text


class DedupCase(str, Enum):
    NEU = "neu"
    F1_TECHNISCHE_DOPPLUNG = "f1_technische_dopplung"
    F2_DUPLIKAT = "f2_duplikat"
    F3_ERSETZT = "f3_ersetzt"
    F4_KONTAKT_BEKANNT = "f4_kontakt_bekannt"


@dataclass(frozen=True)
class ExistingLead:
    """Ausschnitt eines Bestands-Leads, wie ihn die Dedup-Abfrage liefert."""

    id: str
    content_hash: str
    email: str
    email_normalized: str
    phone_raw: str | None
    phone_e164: str | None
    street: str
    postal_code: str | None
    city: str
    name_raw: str | None
    is_owner: bool | None
    contact_time_preference: str | None
    message: str | None
    heard_about: str | None
    status: str
    assigned_to: str | None
    contacted_at: datetime | None
    lead_nummer: int


@dataclass(frozen=True)
class DedupDecision:
    case: DedupCase
    matched_lead_id: str | None


def dedup_decision(
    *,
    is_token_replay: bool,
    new_content_hash: str,
    new_email_normalized: str,
    new_phone_e164: str | None,
    new_street: str,
    new_city: str,
    candidate: ExistingLead | None,
) -> DedupDecision:
    if is_token_replay:
        return DedupDecision(case=DedupCase.F1_TECHNISCHE_DOPPLUNG, matched_lead_id=None)

    if candidate is None:
        return DedupDecision(case=DedupCase.NEU, matched_lead_id=None)

    if candidate.content_hash == new_content_hash:
        return DedupDecision(case=DedupCase.F2_DUPLIKAT, matched_lead_id=candidate.id)

    address_matches = canonical_text(candidate.street) == canonical_text(
        new_street
    ) and canonical_text(candidate.city) == canonical_text(new_city)
    if address_matches:
        return DedupDecision(case=DedupCase.F3_ERSETZT, matched_lead_id=candidate.id)

    person_matches = candidate.email_normalized == new_email_normalized or (
        new_phone_e164 is not None and candidate.phone_e164 == new_phone_e164
    )
    if person_matches:
        return DedupDecision(case=DedupCase.F4_KONTAKT_BEKANNT, matched_lead_id=candidate.id)

    raise ValueError(
        "dedup_decision: candidate ohne Person- oder Grundstück-Match übergeben "
        "- die aufrufende Abfrage sollte nur echte Kandidaten liefern."
    )
