from core.agent_scheduler import parse_cadence


def test_parse_hourly():
    assert parse_cadence("every hour")["interval_sec"] == 3600
    assert parse_cadence("hourly")["interval_sec"] == 3600


def test_parse_every_n_minutes():
    assert parse_cadence("every 30 minutes")["interval_sec"] == 1800
    assert parse_cadence("every 5 mins")["interval_sec"] == 300


def test_parse_every_n_hours():
    assert parse_cadence("every 6 hours")["interval_sec"] == 21600


def test_parse_twice_a_day():
    assert parse_cadence("twice a day")["interval_sec"] == 43200


def test_parse_daily():
    assert parse_cadence("daily")["interval_sec"] == 86400
    assert parse_cadence("every day")["interval_sec"] == 86400


def test_parse_daily_with_time_sets_anchor_hour():
    cad = parse_cadence("every day at 8am")
    assert cad["interval_sec"] == 86400
    assert cad["anchor_iso"] is not None
    # anchor hour should be 08:00
    from datetime import datetime
    assert datetime.fromisoformat(cad["anchor_iso"]).hour == 8


def test_parse_weekly():
    cad = parse_cadence("every Monday morning")
    assert cad["interval_sec"] == 604800
    assert cad["anchor_iso"] is not None


def test_parse_garbage_returns_none():
    assert parse_cadence("blarg flooble") is None
    assert parse_cadence("") is None
