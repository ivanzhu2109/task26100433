"""Resolve nominal local wall-clock datetimes to UTC instants.

Handles DST-style gaps (nonexistent wall times) and folds (repeated wall
times) using only ``zoneinfo`` round-trip checks, so no transition-table
access is needed.
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc

_MAX_FORWARD_SEARCH = dt.timedelta(days=3)


def _valid_utc_instants(
    naive: dt.datetime, tz: ZoneInfo
) -> List[dt.datetime]:
    """UTC instants whose local wall time equals ``naive`` exactly."""
    instants: List[dt.datetime] = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=tz, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(tz).replace(tzinfo=None) == naive:
            if utc not in instants:
                instants.append(utc)
    instants.sort()
    return instants


def _exists(naive: dt.datetime, tz: ZoneInfo) -> bool:
    aware = naive.replace(tzinfo=tz, fold=0)
    return aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == naive


def _first_valid_wall_at_or_after(
    naive: dt.datetime, tz: ZoneInfo
) -> Optional[dt.datetime]:
    """Earliest existing wall time >= ``naive`` (may cross later dates)."""
    if _exists(naive, tz):
        return naive
    # Bracket the next valid second by doubling the step.
    step = dt.timedelta(seconds=60)
    upper = naive
    limit = naive + _MAX_FORWARD_SEARCH
    while True:
        upper = min(upper + step, limit)
        if _exists(upper, tz):
            break
        if upper >= limit:
            return None
        step = min(step * 2, dt.timedelta(hours=6))
    # Binary search between last-invalid (lo) and first-valid (hi).
    lo, hi = naive, upper
    while (hi - lo) > dt.timedelta(seconds=1):
        mid = lo + (hi - lo) / 2
        mid = mid.replace(microsecond=0)
        if mid <= lo:
            mid = lo + dt.timedelta(seconds=1)
        if _exists(mid, tz):
            hi = mid
        else:
            lo = mid
    return hi


def resolve_send_instant(
    nominal_date: dt.date, send_time: dt.time, tz: ZoneInfo
) -> Optional[dt.datetime]:
    """UTC instant for ``send_time`` on ``nominal_date`` in ``tz``.

    Returns None when the whole local date does not exist. Otherwise, when
    the wall time is missing (gap), the earliest valid wall time not before
    the nominal local datetime is used, possibly on a later date. When the
    chosen wall time occurs twice (fold), the earlier UTC instant wins.
    """
    midnight = dt.datetime.combine(nominal_date, dt.time(0, 0, 0))
    day_start = _first_valid_wall_at_or_after(midnight, tz)
    if day_start is None or day_start.date() != nominal_date:
        return None  # the entire local date is skipped in this timezone

    target = dt.datetime.combine(nominal_date, send_time)
    wall = _first_valid_wall_at_or_after(target, tz)
    if wall is None:
        return None
    instants = _valid_utc_instants(wall, tz)
    return instants[0] if instants else None
