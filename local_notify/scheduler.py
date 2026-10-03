"""In-memory scheduler producing delivery candidates for UTC query ranges."""

from __future__ import annotations

import datetime as dt
from typing import Dict, List
from zoneinfo import ZoneInfo

from .quiet import apply_quiet_hours
from .resolution import resolve_send_instant
from .types import Candidate, Frequency, Plan

UTC = dt.timezone.utc
# A nominal date can only affect instants up to this far past its local
# datetime (whole-day gap + quiet-hours deferral), so older nominal dates
# can never fall into a query window.
_MAX_SHIFT = dt.timedelta(days=12)


class Scheduler:
    def __init__(self) -> None:
        self._plans: Dict[str, Plan] = {}

    def register(self, plan: Plan) -> None:
        if plan.plan_id in self._plans:
            raise ValueError(f"plan already registered: {plan.plan_id!r}")
        if plan.frequency is Frequency.WEEKLY and plan.weekday is None:
            raise ValueError("weekly plans require a weekday (0=Monday)")
        if plan.weekday is not None and not 0 <= plan.weekday <= 6:
            raise ValueError("weekday must be in 0..6")
        if plan.nominal_end_date < plan.nominal_start_date:
            raise ValueError("nominal_end_date before nominal_start_date")
        ZoneInfo(plan.timezone)  # validate IANA key eagerly
        self._plans[plan.plan_id] = plan

    def _nominal_dates(self, plan: Plan):
        if plan.frequency is Frequency.DAILY:
            day = plan.nominal_start_date
            while day <= plan.nominal_end_date:
                yield day
                day += dt.timedelta(days=1)
        else:
            day = plan.nominal_start_date
            day += dt.timedelta(days=(plan.weekday - day.weekday()) % 7)
            while day <= plan.nominal_end_date:
                yield day
                day += dt.timedelta(days=7)

    def query(
        self, start_utc: dt.datetime, end_utc: dt.datetime
    ) -> List[Candidate]:
        """Candidates with deliver_at_utc in [start_utc, end_utc).

        Querying never mutates plans. Identity is (plan_id, nominal_date);
        deferral never changes identity, and distinct nominal dates keep
        their own candidates even when they land on the same UTC second.
        """
        start = start_utc.astimezone(UTC)
        end = end_utc.astimezone(UTC)
        if end <= start:
            return []
        candidates: List[Candidate] = []
        for plan in self._plans.values():
            tz = ZoneInfo(plan.timezone)
            for nominal_date in self._nominal_dates(plan):
                # Cheap skip: this nominal date cannot reach the window.
                latest_local = dt.datetime.combine(
                    nominal_date, plan.send_time
                ).replace(tzinfo=UTC)
                if latest_local + _MAX_SHIFT < start:
                    continue
                instant = resolve_send_instant(nominal_date, plan.send_time, tz)
                if instant is None:
                    continue
                instant = apply_quiet_hours(instant, tz, plan.quiet_hours)
                if start <= instant < end:
                    candidates.append(
                        Candidate(plan.plan_id, nominal_date, instant)
                    )
        candidates.sort(key=lambda c: (c.deliver_at_utc, c.plan_id, c.nominal_date))
        return candidates
