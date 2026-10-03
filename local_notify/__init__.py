"""Local-time notification scheduling library.

Plans are registered in memory and never mutated afterwards. The scheduler
only produces delivery candidates; it does not send anything.
"""

from .types import Frequency, QuietHours, Plan, Candidate
from .scheduler import Scheduler

__all__ = ["Frequency", "QuietHours", "Plan", "Candidate", "Scheduler"]
