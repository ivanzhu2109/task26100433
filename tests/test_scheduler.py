"""Automated tests for the local-time notification scheduler.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import unittest
from datetime import date, datetime, time, timezone

from local_scheduler import Frequency, QuietHours, Schedule, Scheduler

UTC = timezone.utc


def dt(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


def daily(schedule_id, tz, send_at, start, end, quiet=None):
    return Schedule(
        schedule_id=schedule_id,
        timezone=tz,
        frequency=Frequency.DAILY,
        send_at=send_at,
        start_date=start,
        end_date=end,
        quiet_hours=quiet,
    )


class DstGapTests(unittest.TestCase):
    def test_nuuk_gap_defers_to_next_local_day(self):
        # America/Nuuk sprang forward 2024-03-30 23:00 -> 2024-03-31 00:00,
        # so 2024-03-30 23:30 never happened locally.
        s = Scheduler()
        s.register(daily("nuuk", "America/Nuuk", time(23, 30),
                         date(2024, 3, 30), date(2024, 3, 30)))
        got = s.query(dt(2024, 3, 1), dt(2024, 4, 1))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].nominal_date, date(2024, 3, 30))
        self.assertEqual(got[0].deliver_at, dt(2024, 3, 31, 1, 0))

    def test_apia_skipped_day_produces_no_candidate(self):
        # Pacific/Apia skipped 2011-12-30 entirely (UTC-10 -> UTC+14).
        s = Scheduler()
        s.register(daily("apia", "Pacific/Apia", time(9, 0),
                         date(2011, 12, 29), date(2011, 12, 31)))
        got = s.query(dt(2011, 12, 1), dt(2012, 1, 15))
        self.assertEqual([c.nominal_date for c in got],
                         [date(2011, 12, 29), date(2011, 12, 31)])
        self.assertEqual(got[0].deliver_at, dt(2011, 12, 29, 19, 0))
        self.assertEqual(got[1].deliver_at, dt(2011, 12, 30, 19, 0))


class FoldAndQuietTests(unittest.TestCase):
    def test_repeated_wall_time_uses_earlier_utc(self):
        # 2024-11-03 01:45 happens twice in New York; pick the EDT one.
        s = Scheduler()
        s.register(daily("ny", "America/New_York", time(1, 45),
                         date(2024, 11, 3), date(2024, 11, 3)))
        got = s.query(dt(2024, 11, 1), dt(2024, 11, 10))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].deliver_at, dt(2024, 11, 3, 5, 45))

    def test_quiet_hours_exit_via_fold_back(self):
        # Quiet 01:30-02:30. Send 01:45 -> 05:45Z (EDT) is quiet, but the
        # clock falls back at 06:00Z to 01:00 EST, which is outside the
        # window, so the result is 06:00Z, not 02:30 EST (07:30Z).
        s = Scheduler()
        s.register(daily("ny", "America/New_York", time(1, 45),
                         date(2024, 11, 3), date(2024, 11, 3),
                         quiet=QuietHours(time(1, 30), time(2, 30))))
        got = s.query(dt(2024, 11, 1), dt(2024, 11, 10))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].deliver_at, dt(2024, 11, 3, 6, 0))
        self.assertEqual(got[0].nominal_date, date(2024, 11, 3))

    def test_quiet_hours_simple_deferral(self):
        s = Scheduler()
        s.register(daily("sh", "Asia/Shanghai", time(22, 0),
                         date(2024, 5, 1), date(2024, 5, 1),
                         quiet=QuietHours(time(21, 0), time(23, 30))))
        got = s.query(dt(2024, 4, 1), dt(2024, 6, 1))
        self.assertEqual(len(got), 1)
        # 23:30 CST == 15:30 UTC
        self.assertEqual(got[0].deliver_at, dt(2024, 5, 1, 15, 30))

    def test_quiet_hours_crossing_midnight(self):
        s = Scheduler()
        s.register(daily("sh", "Asia/Shanghai", time(23, 0),
                         date(2024, 5, 1), date(2024, 5, 1),
                         quiet=QuietHours(time(22, 0), time(6, 0))))
        got = s.query(dt(2024, 4, 1), dt(2024, 6, 1))
        self.assertEqual(len(got), 1)
        # Deferred to 2024-05-02 06:00 CST == 2024-05-01 22:00 UTC.
        self.assertEqual(got[0].deliver_at, dt(2024, 5, 1, 22, 0))
        self.assertEqual(got[0].nominal_date, date(2024, 5, 1))

    def test_equal_quiet_bounds_disable_quiet_hours(self):
        s = Scheduler()
        s.register(daily("sh", "Asia/Shanghai", time(22, 0),
                         date(2024, 5, 1), date(2024, 5, 1),
                         quiet=QuietHours(time(22, 0), time(22, 0))))
        got = s.query(dt(2024, 4, 1), dt(2024, 6, 1))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].deliver_at, dt(2024, 5, 1, 14, 0))


class QuerySemanticsTests(unittest.TestCase):
    def test_range_is_start_inclusive_end_exclusive(self):
        s = Scheduler()
        s.register(daily("sh", "Asia/Shanghai", time(8, 0),
                         date(2024, 5, 1), date(2024, 5, 3)))
        # Sends at 00:00 UTC on May 1, 2, 3.
        got = s.query(dt(2024, 5, 1), dt(2024, 5, 3))
        self.assertEqual([c.deliver_at for c in got], [dt(2024, 5, 1), dt(2024, 5, 2)])
        got = s.query(dt(2024, 5, 1, 0, 0, 1), dt(2024, 5, 4))
        self.assertEqual([c.deliver_at for c in got], [dt(2024, 5, 2), dt(2024, 5, 3)])

    def test_deferred_candidate_from_before_query_start_is_found(self):
        s = Scheduler()
        s.register(daily("sh", "Asia/Shanghai", time(23, 0),
                         date(2024, 5, 1), date(2024, 5, 1),
                         quiet=QuietHours(time(22, 0), time(6, 0))))
        # Final instant is 2024-05-01 22:00 UTC; the query starts after the
        # nominal send time but still includes the deferred instant.
        got = s.query(dt(2024, 5, 1, 16, 0), dt(2024, 5, 2))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].nominal_date, date(2024, 5, 1))
        self.assertEqual(got[0].deliver_at, dt(2024, 5, 1, 22, 0))

    def test_query_does_not_mutate_and_is_repeatable(self):
        s = Scheduler()
        s.register(daily("sh", "Asia/Shanghai", time(8, 0),
                         date(2024, 5, 1), date(2024, 5, 2)))
        first = s.query(dt(2024, 5, 1), dt(2024, 5, 4))
        second = s.query(dt(2024, 5, 1), dt(2024, 5, 4))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)

    def test_distinct_nominal_dates_keep_separate_candidates(self):
        # Nuuk 2024-03-30 23:30 falls in the DST gap and resolves to
        # 2024-03-31 00:00 local; the 00:00-23:30 quiet window then defers
        # it to 2024-03-31 23:30 local == 2024-04-01T00:30:00Z, which is
        # exactly where the 2024-03-31 nominal date lands. Both candidates
        # must survive on the same UTC second.
        s = Scheduler()
        s.register(daily("nuuk", "America/Nuuk", time(23, 30),
                         date(2024, 3, 30), date(2024, 3, 31),
                         quiet=QuietHours(time(0, 0), time(23, 30))))
        got = s.query(dt(2024, 3, 1), dt(2024, 4, 1))
        self.assertEqual(got, [])
        got = s.query(dt(2024, 4, 1), dt(2024, 5, 1))
        self.assertEqual(len(got), 2)
        self.assertEqual([c.nominal_date for c in got],
                         [date(2024, 3, 30), date(2024, 3, 31)])
        self.assertEqual(got[0].deliver_at, got[1].deliver_at)
        self.assertEqual(got[0].deliver_at, dt(2024, 4, 1, 0, 30))

    def test_weekly_frequency_and_date_range(self):
        s = Scheduler()
        s.register(Schedule(
            schedule_id="wk",
            timezone="Asia/Shanghai",
            frequency=Frequency.WEEKLY,
            weekday=2,  # Wednesday
            send_at=time(9, 0),
            start_date=date(2024, 5, 1),
            end_date=date(2024, 5, 31),
        ))
        got = s.query(dt(2024, 4, 1), dt(2024, 7, 1))
        self.assertEqual([c.nominal_date for c in got],
                         [date(2024, 5, 1), date(2024, 5, 8),
                          date(2024, 5, 15), date(2024, 5, 22), date(2024, 5, 29)])
        self.assertTrue(all(
            c.deliver_at == datetime(c.nominal_date.year, c.nominal_date.month,
                                     c.nominal_date.day, 1, 0, tzinfo=UTC)
            for c in got
        ))

    def test_deferral_may_cross_beyond_nominal_end_date(self):
        # The nominal range only constrains nominal dates, not deferrals.
        s = Scheduler()
        s.register(daily("sh", "Asia/Shanghai", time(23, 0),
                         date(2024, 5, 1), date(2024, 5, 1),
                         quiet=QuietHours(time(22, 0), time(6, 0))))
        got = s.query(dt(2024, 5, 1, 21, 0), dt(2024, 5, 3))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].deliver_at, dt(2024, 5, 1, 22, 0))


class RegistrationTests(unittest.TestCase):
    def test_duplicate_id_rejected(self):
        s = Scheduler()
        s.register(daily("a", "Asia/Shanghai", time(8, 0),
                         date(2024, 5, 1), date(2024, 5, 1)))
        with self.assertRaises(ValueError):
            s.register(daily("a", "Asia/Shanghai", time(9, 0),
                             date(2024, 5, 1), date(2024, 5, 1)))

    def test_invalid_timezone_rejected(self):
        s = Scheduler()
        with self.assertRaises(ValueError):
            s.register(daily("bad", "Not/AZone", time(8, 0),
                             date(2024, 5, 1), date(2024, 5, 1)))

    def test_weekly_requires_weekday(self):
        s = Scheduler()
        with self.assertRaises(ValueError):
            s.register(Schedule("w", "Asia/Shanghai", Frequency.WEEKLY,
                                time(8, 0), date(2024, 5, 1), date(2024, 5, 31)))

    def test_invalid_query_range_rejected(self):
        s = Scheduler()
        with self.assertRaises(ValueError):
            s.query(dt(2024, 5, 2), dt(2024, 5, 1))


if __name__ == "__main__":
    unittest.main()
