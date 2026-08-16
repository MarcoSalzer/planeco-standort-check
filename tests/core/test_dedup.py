import pytest

from app.core.dedup import DedupCase, ExistingLead, dedup_decision


def _candidate(**overrides) -> ExistingLead:
    defaults = dict(
        id="lead-1",
        content_hash="hash-alt",
        email="tom.ahrens@example.com",
        email_normalized="tom.ahrens@example.com",
        phone_raw="040 123456",
        phone_e164="+4940123456",
        street="Musterstraße 12",
        postal_code="20095",
        city="Hamburg",
        name_raw="Tom Ahrens",
        is_owner=True,
        contact_time_preference="vormittags",
        message=None,
        heard_about="Empfehlung",
        status="kontaktiert",
        assigned_to="anna",
        contacted_at=None,
    )
    defaults.update(overrides)
    return ExistingLead(**defaults)


def _base_new(**overrides):
    defaults = dict(
        is_token_replay=False,
        new_content_hash="hash-neu",
        new_email_normalized="tom.ahrens@example.com",
        new_phone_e164="+4940123456",
        new_street="Musterstraße 12",
        new_city="Hamburg",
        candidate=None,
    )
    defaults.update(overrides)
    return defaults


def test_f1_technische_dopplung_gewinnt_ungeachtet_des_restes():
    decision = dedup_decision(**_base_new(is_token_replay=True, candidate=_candidate()))
    assert decision.case == DedupCase.F1_TECHNISCHE_DOPPLUNG
    assert decision.matched_lead_id is None


def test_neu_ohne_kandidat():
    decision = dedup_decision(**_base_new(candidate=None))
    assert decision.case == DedupCase.NEU
    assert decision.matched_lead_id is None


def test_f2_identischer_content_hash():
    candidate = _candidate(content_hash="gleicher-hash")
    decision = dedup_decision(**_base_new(new_content_hash="gleicher-hash", candidate=candidate))
    assert decision.case == DedupCase.F2_DUPLIKAT
    assert decision.matched_lead_id == candidate.id


def test_f3_adresse_matcht_person_matcht_nicht():
    candidate = _candidate(
        content_hash="hash-alt",
        email_normalized="andere@example.com",
        phone_e164="+4940999999",
        street="Musterstraße 12",
        city="Hamburg",
    )
    decision = dedup_decision(
        **_base_new(
            new_content_hash="hash-neu",
            new_email_normalized="tom.ahrens@example.com",
            new_phone_e164="+4940123456",
            new_street="musterstraße   12",  # Format-Variante, muss trotzdem matchen
            new_city="HAMBURG",
            candidate=candidate,
        )
    )
    assert decision.case == DedupCase.F3_ERSETZT
    assert decision.matched_lead_id == candidate.id


def test_f3_adresse_matcht_und_person_matcht_bleibt_f3():
    candidate = _candidate(content_hash="hash-alt", street="Musterstraße 12", city="Hamburg")
    decision = dedup_decision(
        **_base_new(new_content_hash="hash-neu", new_street="Musterstraße 12", new_city="Hamburg", candidate=candidate)
    )
    assert decision.case == DedupCase.F3_ERSETZT


def test_f4_nur_person_matcht_adresse_nicht():
    candidate = _candidate(
        content_hash="hash-alt",
        email_normalized="tom.ahrens@example.com",
        phone_e164="+4940123456",
        street="Alte Straße 1",
        city="Bremen",
    )
    decision = dedup_decision(
        **_base_new(
            new_content_hash="hash-neu",
            new_email_normalized="tom.ahrens@example.com",
            new_street="Neue Straße 2",
            new_city="Hamburg",
            candidate=candidate,
        )
    )
    assert decision.case == DedupCase.F4_KONTAKT_BEKANNT
    assert decision.matched_lead_id == candidate.id


def test_f4_matcht_ueber_telefon_statt_email():
    candidate = _candidate(
        content_hash="hash-alt",
        email_normalized="andere@example.com",
        phone_e164="+4940123456",
        street="Alte Straße 1",
        city="Bremen",
    )
    decision = dedup_decision(
        **_base_new(
            new_content_hash="hash-neu",
            new_email_normalized="neu@example.com",
            new_phone_e164="+4940123456",
            new_street="Neue Straße 2",
            new_city="Hamburg",
            candidate=candidate,
        )
    )
    assert decision.case == DedupCase.F4_KONTAKT_BEKANNT


def test_candidate_ohne_jedes_match_ist_programmfehler():
    candidate = _candidate(
        content_hash="hash-alt",
        email_normalized="andere@example.com",
        phone_e164="+4940999999",
        street="Alte Straße 1",
        city="Bremen",
    )
    with pytest.raises(ValueError):
        dedup_decision(
            **_base_new(
                new_content_hash="hash-neu",
                new_email_normalized="neu@example.com",
                new_phone_e164="+4940123456",
                new_street="Neue Straße 2",
                new_city="Hamburg",
                candidate=candidate,
            )
        )
