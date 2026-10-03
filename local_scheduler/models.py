"""Data types for the local-time notification scheduler.

All times are second-precision. "Nominal date" means the local plan date
before any deferral caused by DST gaps or quiet hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Optional


class Frequency(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(frozen=True)
class QuietHours:
    """Daily quiet window in local wall-clock time.

    Start is inclusive, end is exclusive. ``start > end`` means the window
    crosses midnight. ``start == end`` disables quiet hours.
    """

    start: time
    end: time


@dataclass(frozen=True)
class Schedule:
    """A registered, immutable plan.

    - ``timezone``: IANA timezone name, e.g. "America/New_York".
    - ``frequency``: DAILY or WEEKLY.
    - ``weekday``: required for WEEKLY (0=Monday .. 6=Sunday), ignored for DAILY.
    - ``send_at``: local wall-clock time of day to send.
    - ``start_date`` / ``end_date``: inclusive nominal-date range.
    - ``quiet_hours``: optional daily quiet window.
    """

    schedule_id: str
    timezone: str
    frequency: Frequency
    send_at: time
    start_date: date
    end_date: date
    weekday: Optional[int] = None
    quiet_hours: Optional[QuietHours] = None


@dataclass(frozen=True)
class Candidate:
    """A delivery candidate produced from one nominal date of one schedule.

    Identity is (schedule_id, nominal_date); deferral never changes it.
    ``deliver_at`` is the final UTC instant (timezone-aware).
    """

    schedule_id: str
    nominal_date: date
    deliver_at: datetime
