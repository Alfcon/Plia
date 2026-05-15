from datetime import datetime

from core.agent_scheduler import compute_next_fire


def test_no_anchor_adds_interval_to_now():
    now = datetime(2026, 5, 14, 14, 0, 0)
    cad = {"interval_sec": 3600, "anchor_iso": None}
    assert compute_next_fire(cad, now) == datetime(2026, 5, 14, 15, 0, 0)


def test_future_anchor_is_used_directly():
    now = datetime(2026, 5, 14, 14, 0, 0)
    cad = {"interval_sec": 86400, "anchor_iso": "2026-05-14T20:00:00"}
    assert compute_next_fire(cad, now) == datetime(2026, 5, 14, 20, 0, 0)


def test_past_anchor_advances_by_whole_intervals():
    now = datetime(2026, 5, 14, 14, 0, 0)
    # anchor was 08:00 today, interval 6h -> next tick after 14:00 is 20:00
    cad = {"interval_sec": 21600, "anchor_iso": "2026-05-14T08:00:00"}
    assert compute_next_fire(cad, now) == datetime(2026, 5, 14, 20, 0, 0)


def test_past_anchor_exactly_on_interval_boundary_moves_forward():
    now = datetime(2026, 5, 14, 14, 0, 0)
    # anchor 08:00, interval 6h -> 14:00 is a boundary; next must be strictly after
    cad = {"interval_sec": 21600, "anchor_iso": "2026-05-14T08:00:00"}
    result = compute_next_fire(cad, now)
    assert result > now
