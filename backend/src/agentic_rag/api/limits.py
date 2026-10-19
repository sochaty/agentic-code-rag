"""Demo-mode limits: questions per IP per hour, and per day overall.

In-memory, so it resets on restart and isn't shared between processes — fine for one demo
machine. The public deployment (M11) can swap in a shared store behind the same interface.
"""

import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Protocol

HOUR = 3600.0


class Limiter(Protocol):
    def admit(self, client: str) -> str | None:
        """None if the question may run; otherwise a reason to show the visitor."""
        ...


class Unlimited:
    def admit(self, client: str) -> str | None:
        return None


class DemoLimiter:
    def __init__(self, per_ip_per_hour: int, per_day: int, clock: "Clock | None" = None) -> None:
        self.per_ip_per_hour = per_ip_per_hour
        self.per_day = per_day
        self._clock = clock or Clock()
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self._day = ""
        self._today = 0
        self._lock = threading.Lock()

    def admit(self, client: str) -> str | None:
        with self._lock:
            now = self._clock.now()
            day = self._clock.day()
            if day != self._day:
                self._day, self._today = day, 0
            if self._today >= self.per_day:
                return "The demo's daily question limit is used up. Please try again tomorrow."
            recent = self._recent[client]
            while recent and now - recent[0] > HOUR:
                recent.popleft()
            if len(recent) >= self.per_ip_per_hour:
                return f"Limit reached: {self.per_ip_per_hour} questions per hour. Try again later."
            recent.append(now)
            self._today += 1
            return None


class Clock:
    def now(self) -> float:
        return time.monotonic()

    def day(self) -> str:
        return datetime.now(UTC).date().isoformat()
