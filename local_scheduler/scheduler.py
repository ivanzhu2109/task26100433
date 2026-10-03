"""In-memory local-time notification scheduler.

Plans are registered once and never mutated. Queries only generate
delivery candidates; nothing is actually sent.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Candidate, Frequency, QuietHours, Schedule

UTC = timezone.utc
_ONE_SECOND = timedelta(seconds=1)
_ONE_DAY = timedelta(days=1)

# Safety margin (in days) for how far a candidate can be deferred past its
# nominal date (quiet hours + DST gap chains stay well below this).
_MAX_DEFER_DAYS = 4


def _local_naive(instant_utc: datetime, tz: ZoneInfo) -> datetime:
    return instant_utc.astimezone(tz).replace(tzinfo=None)


def _offset(instant_utc: datetime, tz: ZoneInfo) -> timedelta:
    return instant_utc.astimezone(tz).utcoffset()


def _exists(naive: datetime, tz: ZoneInfo) -> bool:
    """True if the naive local wall time occurs in ``tz``."""
    for fold in (0, 1):
        aware = naive.replace(tzinfo=tz, fold=fold)
        if aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == naive:
            return True
    return False


def _to_utc_earliest(naive: datetime, tz: ZoneInfo) -> datetime:
    """UTC instant of an existing wall time; earlier instant when repeated."""
    return min(
        naive.replace(tzinfo=tz, fold=fold).astimezone(UTC) for fold in (0, 1)
    )


def _resolve_forward(naive: datetime, tz: ZoneInfo) -> datetime:
    """UTC instant of the earliest valid wall time >= ``naive``.

    If ``naive`` exists, its (earlier) instant is returned. If it falls in a
    DST gap, the transition instant itself is returned: its wall time is the
    first valid wall time after the gap, possibly on a later local date.
    """
    if _exists(naive, tz):
        return _to_utc_earliest(naive, tz)
    # In a gap: fold=1 uses the post-transition offset, fold=0 the pre-
    # transition offset, so the transition instant lies in (lo, hi].
    lo = naive.replace(tzinfo=tz, fold=1).astimezone(UTC)
    hi = naive.replace(tzinfo=tz, fold=0).astimezone(UTC)
    while hi - lo > _ONE_SECOND:
        mid = lo + (hi - lo) // 2
        if _local_naive(mid, tz) >= naive:
            hi = mid
        else:
            lo = mid
    return hi.replace(microsecond=0)


def _day_exists(day: date, tz: ZoneInfo) -> bool:
    """True if at least one wall-clock moment of the local date exists."""
    midnight = datetime.combine(day, time.min)
    if _exists(midnight, tz):
        return True
    return _local_naive(_resolve_forward(midnight, tz), tz).date() == day


def _bisect_transition(
    lo: datetime, hi: datetime, tz: ZoneInfo, offset_lo: timedelta
) -> datetime:
    """First UTC second in (lo, hi] whose UTC offset differs from offset_lo."""
    while hi - lo > _ONE_SECOND:
        mid = lo + (hi - lo) // 2
        if _offset(mid, tz) != offset_lo:
            hi = mid
        else:
            lo = mid
    return hi.replace(microsecond=0)


def _next_transition(
    start: datetime, end: datetime, tz: ZoneInfo
) -> Optional[datetime]:
    """First UTC-offset transition instant in (start, end], or None."""
    step = timedelta(hours=1)
    prev = start
    prev_off = _offset(start, tz)
    cur = start + step
    while cur < end:
        off = _offset(cur, tz)
        if off != prev_off:
            return _bisect_transition(prev, cur, tz, prev_off)
        prev, prev_off = cur, off
        cur += step
    if _offset(end, tz) != prev_off:
        return _bisect_transition(prev, end, tz, prev_off)
    return None


def _in_window(tod: time, quiet: QuietHours) -> bool:
    if quiet.start < quiet.end:
        return quiet.start <= tod < quiet.end
    return tod >= quiet.start or tod < quiet.end


def _defer_quiet(
    instant_utc: datetime, tz: ZoneInfo, quiet: QuietHours
) -> datetime:
    """Earliest UTC second >= instant_utc whose local time is outside quiet.

    Judgement always uses the local time-of-day of the actual UTC instant,
    so repeated hours after a fall-back transition are each evaluated as
    they occur.
    """
    t = instant_utc
    while True:
        local = _local_naive(t, tz)
        if not _in_window(local.time(), quiet):
            return t
        if quiet.start < quiet.end:
            end_naive = datetime.combine(local.date(), quiet.end)
        elif local.time() >= quiet.start:
            end_naive = datetime.combine(local.date() + _ONE_DAY, quiet.end)
        else:
            end_naive = datetime.combine(local.date(), quiet.end)
        t_end = _resolve_forward(end_naive, tz)
        # A clock fold-back between t and t_end may exit the window earlier
        # than the nominal window end.
        transition = _next_transition(t, t_end, tz)
        t = t_end if transition is None else transition


class Scheduler:
    """Holds registered schedules and answers UTC-range candidate queries."""

    def __init__(self) -> None:
        self._schedules: Dict[str, Schedule] = {}
        self._tz: Dict[str, ZoneInfo] = {}

    def register(self, schedule: Schedule) -> None:
        """Register a schedule. Raises ValueError on invalid input or
        duplicate schedule_id."""
        if not schedule.schedule_id:
            raise ValueError("schedule_id must be non-empty")
        if schedule.schedule_id in self._schedules:
            raise ValueError(f"duplicate schedule_id: {schedule.schedule_id}")
        try:
            tz = ZoneInfo(schedule.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {schedule.timezone}") from exc
        if schedule.frequency is Frequency.WEEKLY:
            if schedule.weekday is None or not 0 <= schedule.weekday <= 6:
                raise ValueError("weekly schedules need weekday in 0..6 (Mon=0)")
        if schedule.start_date > schedule.end_date:
            raise ValueError("start_date must be <= end_date")
        if schedule.send_at.microsecond:
            raise ValueError("send_at must have second precision")
        quiet = schedule.quiet_hours
        if quiet is not None:
            if quiet.start.microsecond or quiet.end.microsecond:
                raise ValueError("quiet hours must have second precision")
            if quiet.start == quiet.end:
                quiet = None  # equal start/end disables quiet hours
        # Store a normalized copy; registered schedules are never mutated.
        normalized = Schedule(
            schedule_id=schedule.schedule_id,
            timezone=schedule.timezone,
            frequency=schedule.frequency,
            send_at=schedule.send_at,
            start_date=schedule.start_date,
            end_date=schedule.end_date,
            weekday=schedule.weekday,
            quiet_hours=quiet,
        )
        self._tz[schedule.schedule_id] = tz
        self._schedules[schedule.schedule_id] = normalized

    def query(self, start_utc: datetime, end_utc: datetime) -> List[Candidate]:
        """Return candidates whose final UTC instant is in [start_utc, end_utc).

        The query never mutates registered schedules. Candidates deferred
        from nominal dates before ``start_utc`` are included when their
        final instant falls inside the range.
        """
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("query bounds must be timezone-aware UTC")
        start_utc = start_utc.astimezone(UTC)
        end_utc = end_utc.astimezone(UTC)
        if start_utc.microsecond or end_utc.microsecond:
            raise ValueError("query bounds must have second precision")
        if not start_utc < end_utc:
            raise ValueError("start_utc must be < end_utc")

        results: List[Candidate] = []
        for schedule in self._schedules.values():
            tz = self._tz[schedule.schedule_id]
            results.extend(self._candidates_for(schedule, tz, start_utc, end_utc))
        results.sort(key=lambda c: (c.deliver_at, c.schedule_id, c.nominal_date))
        return results

    def _candidates_for(
        self,
        schedule: Schedule,
        tz: ZoneInfo,
        start_utc: datetime,
        end_utc: datetime,
    ) -> List[Candidate]:
        # Nominal dates whose final instant can still land inside the query
        # range: deferral only moves forward and is bounded by _MAX_DEFER_DAYS.
        first = max(schedule.start_date, (start_utc - timedelta(days=_MAX_DEFER_DAYS)).date())
        last = min(schedule.end_date, (end_utc + _ONE_DAY).date())
        out: List[Candidate] = []
        day = first
        while day <= last:
            if schedule.frequency is Frequency.WEEKLY and day.weekday() != schedule.weekday:
                day += _ONE_DAY
                continue
            candidate = self._candidate_for_date(schedule, tz, day)
            if candidate is not None and start_utc <= candidate.deliver_at < end_utc:
                out.append(candidate)
            day += _ONE_DAY
        return out

    def _candidate_for_date(
        self, schedule: Schedule, tz: ZoneInfo, day: date
    ) -> Optional[Candidate]:
        if not _day_exists(day, tz):
            return None
        send_naive = datetime.combine(day, schedule.send_at)
        instant = _resolve_forward(send_naive, tz)
        if schedule.quiet_hours is not None:
            instant = _defer_quiet(instant, tz, schedule.quiet_hours)
        return Candidate(
            schedule_id=schedule.schedule_id,
            nominal_date=day,
            deliver_at=instant,
        )
