"""Type definitions for the local-time notification scheduler."""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass
from typing import Optional


class Frequency(enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(frozen=True)
class QuietHours:
    """Daily do-not-disturb window in local wall-clock time.

    start == end means the window is disabled. start > end crosses midnight.
    The window is start-inclusive and end-exclusive.
    """

    start: dt.time
    end: dt.time


@dataclass(frozen=True)
class Plan:
    """A registered notification plan. Immutable after registration.

    nominal_start_date / nominal_end_date bound the *nominal* local dates
    (inclusive on both ends), i.e. the planned local dates before any
    deferral. They do not constrain deferred results.
    """

    plan_id: str
    timezone: str
    frequency: Frequency
    weekday: Optional[int]  # 0=Monday .. 6=Sunday; only used for WEEKLY
    send_time: dt.time      # local wall-clock send time, second precision
    nominal_start_date: dt.date
    nominal_end_date: dt.date
    quiet_hours: Optional[QuietHours] = None


@dataclass(frozen=True)
class Candidate:
    """A delivery candidate: identity = (plan_id, nominal_date)."""

    plan_id: str
    nominal_date: dt.date
    deliver_at_utc: dt.datetime  # timezone-aware UTC instant
