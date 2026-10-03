"""Do-not-disturb (quiet hours) deferral.

Judgement uses the local wall-clock time-of-day of the actual UTC instant.
The window is start-inclusive, end-exclusive; start > end crosses midnight;
start == end disables the window. When an instant falls inside the window,
it is deferred to the earliest UTC second >= the original instant that is
not inside the window. Repeated hours after a fold are judged by their
current local time-of-day each time.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from .types import QuietHours

UTC = dt.timezone.utc
_ONE_SECOND = dt.timedelta(seconds=1)
_MAX_DEFERRAL = dt.timedelta(days=8)


def _in_window(tod: dt.time, quiet: QuietHours) -> bool:
    start, end = quiet.start, quiet.end
    if start == end:
        return False
    if start < end:
        return start <= tod < end
    return tod >= start or tod < end


def _window_end_naive(local: dt.datetime, quiet: QuietHours) -> dt.datetime:
    """Naive local datetime at which the current window occurrence ends."""
    start, end = quiet.start, quiet.end
    if start < end:
        end_date = local.date()
    else:  # crosses midnight
        end_date = local.date() + dt.timedelta(days=1) if local.time() >= start else local.date()
    return dt.datetime.combine(end_date, end)


def _first_offset_change_after(
    instant: dt.datetime, tz: ZoneInfo, horizon: dt.datetime
) -> dt.datetime | None:
    """First UTC second in (instant, horizon] whose UTC offset differs."""
    offset = instant.astimezone(tz).utcoffset()
    if horizon.astimezone(tz).utcoffset() == offset:
        return None
    lo, hi = instant, horizon
    while (hi - lo) > _ONE_SECOND:
        mid = lo + (hi - lo) / 2
        mid = mid.replace(microsecond=0)
        if mid <= lo:
            mid = lo + _ONE_SECOND
        if mid.astimezone(tz).utcoffset() == offset:
            lo = mid
        else:
            hi = mid
    return hi


def apply_quiet_hours(
    instant: dt.datetime, tz: ZoneInfo, quiet: QuietHours | None
) -> dt.datetime:
    """Defer ``instant`` (UTC, second precision) out of the quiet window."""
    if quiet is None or quiet.start == quiet.end:
        return instant
    t = instant.replace(microsecond=0).astimezone(UTC)
    deadline = t + _MAX_DEFERRAL
    while _in_window(t.astimezone(tz).time(), quiet):
        if t >= deadline:
            raise ValueError("quiet-hours deferral exceeded safety bound")
        local = t.astimezone(tz)
        end_naive = _window_end_naive(local, quiet)
        # UTC at which the wall clock reaches the window end, assuming the
        # current offset holds; a transition may end the window earlier.
        exit_utc = (end_naive - local.utcoffset()).replace(tzinfo=UTC)
        transition = _first_offset_change_after(t, tz, min(exit_utc, deadline))
        nxt = exit_utc if transition is None else min(exit_utc, transition)
        t = max(nxt, t + _ONE_SECOND)
    return t
