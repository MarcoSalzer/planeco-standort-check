from datetime import datetime, timezone

import pytest

from app.core.display import format_berlin_datetime


def test_winter_utc_wird_um_eine_stunde_versetzt_cet():
    value = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    assert format_berlin_datetime(value) == "15.01.2026 11:00"


def test_sommer_utc_wird_um_zwei_stunden_versetzt_cest():
    value = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
    assert format_berlin_datetime(value) == "15.07.2026 12:00"


def test_naive_datetime_wirft_fehler_statt_falsch_anzuzeigen():
    with pytest.raises(ValueError):
        format_berlin_datetime(datetime(2026, 1, 15, 10, 0))
