from datetime import datetime, timezone

from bot.timeutil import (
    format_date,
    format_duration,
    parse_duration_seconds,
    parse_natural_time,
    snowflake_to_datetime,
)


def test_parse_duration_seconds_units():
    assert parse_duration_seconds("10m") == 600
    assert parse_duration_seconds("2h") == 7200
    assert parse_duration_seconds("1d") == 86400
    assert parse_duration_seconds("1w") == 604800
    assert parse_duration_seconds("45s") == 45


def test_parse_duration_seconds_case_insensitive():
    assert parse_duration_seconds("2H") == 7200


def test_parse_duration_seconds_rejects_garbage():
    assert parse_duration_seconds("soon") is None
    assert parse_duration_seconds("2") is None
    assert parse_duration_seconds("") is None


def test_parse_natural_time_relative_duration():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = parse_natural_time("in 2 hours take out the trash", now)
    assert result is not None
    remind_at, message = result
    assert message == "take out the trash"
    assert remind_at == datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)


def test_parse_natural_time_accepts_old_rigid_tokens():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = parse_natural_time("2h take out the trash", now)
    assert result is not None
    remind_at, message = result
    assert message == "take out the trash"
    assert remind_at == datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)


def test_parse_natural_time_expression_after_message():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = parse_natural_time("take out the trash in 10 minutes", now)
    assert result is not None
    _, message = result
    assert message == "take out the trash"


def test_parse_natural_time_rejects_no_time_expression():
    assert parse_natural_time("asdfasdf not a time at all") is None


def test_parse_natural_time_rejects_no_message_left_over():
    assert parse_natural_time("in 30 seconds") is None


def test_parse_natural_time_can_resolve_to_the_past():
    # The function itself doesn't reject past times, callers (the !remind
    # command) decide what to do with a remind_at that's <= now.
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    result = parse_natural_time("yesterday do laundry", now)
    assert result is not None
    remind_at, _ = result
    assert remind_at < now


def test_format_duration():
    assert format_duration(5) == "5s"
    assert format_duration(65) == "1m 5s"
    assert format_duration(3665) == "1h 1m 5s"
    assert format_duration(90065) == "1d 1h 1m 5s"


def test_format_date_handles_none():
    assert format_date(None) == "Unknown"


def test_format_date_formats_a_real_datetime():
    assert format_date(datetime(2026, 3, 4, tzinfo=timezone.utc)) == "2026-03-04"


def test_snowflake_to_datetime_roundtrip():
    from bot.timeutil import FLUXER_EPOCH_MS

    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ms_since_epoch = int(dt.timestamp() * 1000) - FLUXER_EPOCH_MS
    fake_snowflake = str(ms_since_epoch << 22)
    decoded = snowflake_to_datetime(fake_snowflake)
    assert decoded is not None
    assert abs((decoded - dt).total_seconds()) < 1


def test_snowflake_to_datetime_rejects_garbage():
    assert snowflake_to_datetime("not-a-number") is None
