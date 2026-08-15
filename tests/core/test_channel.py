import pytest

from app.core.channel import derive_channel


def test_derive_channel_priority_1_utm_source():
    channel, source = derive_channel(
        utm_source="google", gclid=None, fbclid=None, referrer=None, heard_about=None
    )
    assert (channel, source) == ("google_ads", "utm")


def test_derive_channel_priority_2_gclid():
    channel, source = derive_channel(
        utm_source=None, gclid="abc123", fbclid=None, referrer=None, heard_about=None
    )
    assert (channel, source) == ("google_ads", "gclid")


def test_derive_channel_priority_3_fbclid():
    channel, source = derive_channel(
        utm_source=None, gclid=None, fbclid="xyz789", referrer=None, heard_about=None
    )
    assert (channel, source) == ("meta_ads", "fbclid")


def test_derive_channel_priority_4_referrer():
    channel, source = derive_channel(
        utm_source=None,
        gclid=None,
        fbclid=None,
        referrer="https://www.google.com/search?q=standort-check",
        heard_about=None,
    )
    assert (channel, source) == ("google_organisch", "referrer")


@pytest.mark.parametrize(
    "referrer",
    [
        "https://www.bing.com/search?q=standort-check",
        "https://duckduckgo.com/?q=standort-check",
    ],
)
def test_derive_channel_referrer_recognizes_other_search_engines(referrer):
    channel, source = derive_channel(
        utm_source=None, gclid=None, fbclid=None, referrer=referrer, heard_about=None
    )
    assert (channel, source) == ("andere_suche", "referrer")


@pytest.mark.parametrize(
    "utm_source",
    ["googlemail", "google-partner-blog"],
)
def test_derive_channel_utm_source_substring_fallback_is_marked_unsicher(utm_source):
    channel, source = derive_channel(
        utm_source=utm_source, gclid=None, fbclid=None, referrer=None, heard_about=None
    )
    assert (channel, source) == ("google_ads", "utm_unsicher")


def test_derive_channel_utm_source_unrecognized_falls_back_to_sonstiges():
    channel, source = derive_channel(
        utm_source="newsletter", gclid=None, fbclid=None, referrer=None, heard_about=None
    )
    assert (channel, source) == ("sonstiges", "utm")


def test_derive_channel_priority_5_heard_about():
    channel, source = derive_channel(
        utm_source=None, gclid=None, fbclid=None, referrer=None, heard_about="Empfehlung"
    )
    assert (channel, source) == ("empfehlung", "selbstauskunft")


def test_derive_channel_priority_6_direkt():
    channel, source = derive_channel(
        utm_source=None, gclid=None, fbclid=None, referrer=None, heard_about=None
    )
    assert (channel, source) == ("direkt", "keine")
