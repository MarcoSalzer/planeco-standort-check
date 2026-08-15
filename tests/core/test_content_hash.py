from app.core.content_hash import content_hash


def _base_kwargs(**overrides):
    kwargs = dict(
        name="Tom Ahrens",
        email_normalized="tom.ahrens@example.com",
        phone_e164="+4940123456",
        street="Musterstraße 12",
        postal_code="20095",
        city="Hamburg",
        is_owner=True,
        contact_time_preference="vormittags",
        message="Bitte um Rückruf",
        heard_about="Empfehlung",
    )
    kwargs.update(overrides)
    return kwargs


def test_content_hash_stable_across_whitespace_and_case_variants():
    original = content_hash(**_base_kwargs())
    variant = content_hash(
        **_base_kwargs(
            street="Musterstraße   12",  # doppeltes Leerzeichen
            city="HAMBURG",              # Großschreibung
            message="  Bitte um Rückruf  ",  # führende/nachgestellte Leerzeichen
        )
    )
    assert original == variant


def test_content_hash_changes_when_address_actually_changes():
    original = content_hash(**_base_kwargs())
    changed = content_hash(**_base_kwargs(city="Berlin"))
    assert original != changed


def test_content_hash_changes_when_phone_changes():
    original = content_hash(**_base_kwargs())
    changed = content_hash(**_base_kwargs(phone_e164="+4940999999"))
    assert original != changed


def test_content_hash_treats_none_and_empty_string_the_same():
    with_none = content_hash(**_base_kwargs(message=None))
    with_empty = content_hash(**_base_kwargs(message=""))
    assert with_none == with_empty
