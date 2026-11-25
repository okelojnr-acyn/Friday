from datetime import UTC, date, datetime

from friday_common.clock import day_bounds, local_date, month_bounds, zone

NAIROBI = zone("Africa/Nairobi")


def test_a_sale_after_local_midnight_is_on_the_local_date():
    # 01:30 in Nairobi on 26 Nov is 22:30 UTC on 25 Nov.
    at = datetime(2026, 11, 25, 22, 30, tzinfo=UTC)
    assert local_date(at, NAIROBI) == date(2026, 11, 26)
    assert local_date(at, UTC) == date(2026, 11, 25)
    assert local_date(at.replace(tzinfo=None), NAIROBI) == date(2026, 11, 26)  # naive = UTC


def test_local_day_and_month_windows_in_utc():
    start, end = day_bounds(date(2026, 11, 26), NAIROBI)
    assert (start, end) == (datetime(2026, 11, 25, 21, tzinfo=UTC), datetime(2026, 11, 26, 21, tzinfo=UTC))
    start, end = month_bounds(2026, 12, NAIROBI)
    assert (start, end) == (datetime(2026, 11, 30, 21, tzinfo=UTC), datetime(2026, 12, 31, 21, tzinfo=UTC))


def test_unknown_or_missing_zone_is_utc():
    assert zone("") is UTC and zone("Mars/Base") is UTC
