import datetime as dt

import pytest

from local_notify import Candidate, Frequency, Plan, QuietHours, Scheduler

UTC = dt.timezone.utc


def utc(y, mo, d, h=0, mi=0, s=0):
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=UTC)


def make_plan(**kw):
    defaults = dict(
        plan_id="p1",
        timezone="UTC",
        frequency=Frequency.DAILY,
        weekday=None,
        send_time=dt.time(9, 0, 0),
        nominal_start_date=dt.date(2024, 1, 1),
        nominal_end_date=dt.date(2024, 1, 1),
        quiet_hours=None,
    )
    defaults.update(kw)
    return Plan(**defaults)


# --- Spec scenario 1: gap pushes send into the next local date -------------

def test_nuuk_gap_defers_to_next_local_midnight():
    s = Scheduler()
    s.register(make_plan(
        timezone="America/Nuuk",
        send_time=dt.time(23, 30),
        nominal_start_date=dt.date(2024, 3, 30),
        nominal_end_date=dt.date(2024, 3, 30),
    ))
    got = s.query(utc(2024, 3, 1), utc(2024, 4, 1))
    assert got == [Candidate("p1", dt.date(2024, 3, 30), utc(2024, 3, 31, 1, 0))]


def test_apia_skipped_whole_day_produces_no_candidate():
    s = Scheduler()
    s.register(make_plan(
        timezone="Pacific/Apia",
        nominal_start_date=dt.date(2011, 12, 29),
        nominal_end_date=dt.date(2011, 12, 31),
    ))
    got = s.query(utc(2011, 12, 1), utc(2012, 1, 10))
    nominal_dates = [c.nominal_date for c in got]
    assert dt.date(2011, 12, 30) not in nominal_dates
    assert nominal_dates == [dt.date(2011, 12, 29), dt.date(2011, 12, 31)]


# --- Spec scenario 2: fold + quiet hours -----------------------------------

def test_new_york_fold_quiet_hours_lands_on_repeated_hour():
    s = Scheduler()
    s.register(make_plan(
        timezone="America/New_York",
        send_time=dt.time(1, 45),
        nominal_start_date=dt.date(2024, 11, 3),
        nominal_end_date=dt.date(2024, 11, 3),
        quiet_hours=QuietHours(dt.time(1, 30), dt.time(2, 30)),
    ))
    got = s.query(utc(2024, 11, 1), utc(2024, 11, 10))
    # Earlier 01:45 (EDT, 05:45Z) is inside quiet hours; the earliest UTC
    # second outside the window is 06:00Z, the folded 01:00 EST - not 02:30.
    assert got == [Candidate("p1", dt.date(2024, 11, 3), utc(2024, 11, 3, 6, 0))]


def test_fold_without_quiet_takes_earlier_utc_instant():
    s = Scheduler()
    s.register(make_plan(
        timezone="America/New_York",
        send_time=dt.time(1, 45),
        nominal_start_date=dt.date(2024, 11, 3),
        nominal_end_date=dt.date(2024, 11, 3),
    ))
    got = s.query(utc(2024, 11, 1), utc(2024, 11, 10))
    assert got == [Candidate("p1", dt.date(2024, 11, 3), utc(2024, 11, 3, 5, 45))]


# --- Frequency -------------------------------------------------------------

def test_daily_plan_yields_one_candidate_per_nominal_date():
    s = Scheduler()
    s.register(make_plan(
        nominal_start_date=dt.date(2024, 1, 1),
        nominal_end_date=dt.date(2024, 1, 3),
    ))
    got = s.query(utc(2024, 1, 1), utc(2024, 2, 1))
    assert [c.nominal_date for c in got] == [
        dt.date(2024, 1, 1), dt.date(2024, 1, 2), dt.date(2024, 1, 3)]
    assert [c.deliver_at_utc for c in got] == [
        utc(2024, 1, 1, 9), utc(2024, 1, 2, 9), utc(2024, 1, 3, 9)]


def test_weekly_plan_only_fires_on_configured_weekday():
    s = Scheduler()
    s.register(make_plan(
        frequency=Frequency.WEEKLY,
        weekday=2,  # Wednesday
        nominal_start_date=dt.date(2024, 1, 1),  # Monday
        nominal_end_date=dt.date(2024, 1, 31),
    ))
    got = s.query(utc(2024, 1, 1), utc(2024, 3, 1))
    assert [c.nominal_date for c in got] == [
        dt.date(2024, 1, 3), dt.date(2024, 1, 10),
        dt.date(2024, 1, 17), dt.date(2024, 1, 24), dt.date(2024, 1, 31)]


def test_weekly_requires_weekday():
    s = Scheduler()
    with pytest.raises(ValueError):
        s.register(make_plan(frequency=Frequency.WEEKLY, weekday=None))


# --- Query window semantics -------------------------------------------------

def test_query_window_is_start_inclusive_end_exclusive():
    s = Scheduler()
    s.register(make_plan(
        nominal_start_date=dt.date(2024, 1, 1),
        nominal_end_date=dt.date(2024, 1, 2),
    ))
    at_start = s.query(utc(2024, 1, 1, 9), utc(2024, 1, 2, 9))
    assert [c.deliver_at_utc for c in at_start] == [utc(2024, 1, 1, 9)]
    empty = s.query(utc(2024, 1, 3, 9), utc(2024, 1, 3, 9))
    assert empty == []


def test_deferred_candidate_from_before_window_is_found():
    # Send 23:00 UTC with quiet 22:00-09:00 defers the Jan 1 candidate to
    # Jan 2 09:00; a query starting Jan 2 must still find it.
    s = Scheduler()
    s.register(make_plan(
        send_time=dt.time(23, 0),
        nominal_start_date=dt.date(2024, 1, 1),
        nominal_end_date=dt.date(2024, 1, 1),
        quiet_hours=QuietHours(dt.time(22, 0), dt.time(9, 0)),
    ))
    got = s.query(utc(2024, 1, 2), utc(2024, 1, 3))
    assert got == [Candidate("p1", dt.date(2024, 1, 1), utc(2024, 1, 2, 9))]


def test_repeated_and_varying_queries_do_not_duplicate_candidates():
    s = Scheduler()
    s.register(make_plan(
        nominal_start_date=dt.date(2024, 1, 1),
        nominal_end_date=dt.date(2024, 1, 2),
    ))
    wide = s.query(utc(2024, 1, 1), utc(2024, 2, 1))
    narrow = s.query(utc(2024, 1, 1), utc(2024, 1, 2))
    wide_again = s.query(utc(2024, 1, 1), utc(2024, 2, 1))
    assert wide == wide_again
    assert len(wide) == 2 and len(narrow) == 1
    assert narrow == wide[:1]


def test_distinct_nominal_dates_sharing_one_utc_second_keep_candidates():
    # Quiet 22:00-09:00 defers nominal day 1 (23:00) to day 2 09:00, exactly
    # where nominal day 2 (09:00) already lands. Both candidates survive.
    s = Scheduler()
    s.register(make_plan(
        send_time=dt.time(23, 0),
        nominal_start_date=dt.date(2024, 1, 1),
        nominal_end_date=dt.date(2024, 1, 1),
        quiet_hours=QuietHours(dt.time(22, 0), dt.time(9, 0)),
    ))
    s.register(make_plan(
        plan_id="p2",
        send_time=dt.time(9, 0),
        nominal_start_date=dt.date(2024, 1, 2),
        nominal_end_date=dt.date(2024, 1, 2),
    ))
    got = s.query(utc(2024, 1, 2, 9), utc(2024, 1, 2, 10))
    assert len(got) == 2
    assert {c.plan_id for c in got} == {"p1", "p2"}
    assert all(c.deliver_at_utc == utc(2024, 1, 2, 9) for c in got)


# --- Quiet hours details ----------------------------------------------------

def test_quiet_hours_disabled_when_start_equals_end():
    s = Scheduler()
    s.register(make_plan(
        quiet_hours=QuietHours(dt.time(9, 0), dt.time(9, 0)),
    ))
    got = s.query(utc(2024, 1, 1), utc(2024, 2, 1))
    assert got == [Candidate("p1", dt.date(2024, 1, 1), utc(2024, 1, 1, 9))]


def test_quiet_window_end_is_exclusive():
    # Instant exactly at the window end is not deferred.
    s = Scheduler()
    s.register(make_plan(
        send_time=dt.time(9, 0),
        quiet_hours=QuietHours(dt.time(22, 0), dt.time(9, 0)),
    ))
    got = s.query(utc(2024, 1, 1), utc(2024, 2, 1))
    assert got == [Candidate("p1", dt.date(2024, 1, 1), utc(2024, 1, 1, 9))]


def test_deferral_keeps_candidate_identity():
    s = Scheduler()
    s.register(make_plan(
        send_time=dt.time(23, 0),
        quiet_hours=QuietHours(dt.time(22, 0), dt.time(9, 0)),
    ))
    got = s.query(utc(2024, 1, 1), utc(2024, 2, 1))
    assert got == [Candidate("p1", dt.date(2024, 1, 1), utc(2024, 1, 2, 9))]


def test_nominal_range_does_not_limit_deferred_result():
    # Deferral may land past nominal_end_date; that is still delivered.
    s = Scheduler()
    s.register(make_plan(
        timezone="America/Nuuk",
        send_time=dt.time(23, 30),
        nominal_start_date=dt.date(2024, 3, 30),
        nominal_end_date=dt.date(2024, 3, 30),
    ))
    got = s.query(utc(2024, 3, 31), utc(2024, 4, 1))
    assert got == [Candidate("p1", dt.date(2024, 3, 30), utc(2024, 3, 31, 1, 0))]


def test_register_rejects_duplicate_plan_id():
    s = Scheduler()
    s.register(make_plan())
    with pytest.raises(ValueError):
        s.register(make_plan())
