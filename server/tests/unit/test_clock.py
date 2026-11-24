from datetime import datetime, timedelta, timezone

from app.core.clock import FrozenClock


def test_frozen_clock_starts_at_the_given_moment():
    moment = datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)
    clock = FrozenClock(moment)
    assert clock.now() == moment


def test_frozen_clock_advance_moves_only_that_clock():
    clock = FrozenClock(datetime(2026, 11, 24, 9, 59, tzinfo=timezone.utc))
    clock.advance(minutes=2)
    assert clock.now() == datetime(2026, 11, 24, 10, 1, tzinfo=timezone.utc)
    assert timedelta(minutes=2).total_seconds() == 120
