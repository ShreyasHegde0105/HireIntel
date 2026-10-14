import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

from app.config import settings


class LimitExceeded(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class DemoLimiter:
    """In-memory abuse and cost guard for a single-process demo deployment.

    - per-client request limits (per minute and per day)
    - a global daily budget of resumes processed, which caps AI spend

    State resets on restart. That is acceptable for a demo; a multi-process
    deployment would need a shared store.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._requests = defaultdict(deque)  # client -> request timestamps in the last 24h
        self._budget_day = self._today()
        self._resumes_today = 0

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    @staticmethod
    def _seconds_until_utc_midnight() -> int:
        now = datetime.now(timezone.utc)
        return max(1, 86400 - (now.hour * 3600 + now.minute * 60 + now.second))

    def check_and_reserve(self, client: str, resume_count: int, now: Optional[float] = None) -> None:
        """Raises LimitExceeded, or records the request and reserves budget for its resumes."""
        now = time.time() if now is None else now
        with self._lock:
            today = self._today()
            if today != self._budget_day:
                self._budget_day = today
                self._resumes_today = 0

            history = self._requests[client]
            while history and history[0] <= now - 86400:
                history.popleft()

            recent = sum(1 for t in history if t > now - 60)
            if recent >= settings.RATE_LIMIT_PER_MINUTE:
                raise LimitExceeded("Too many requests. Please wait a minute and try again.", 60)
            if len(history) >= settings.RATE_LIMIT_PER_DAY:
                raise LimitExceeded("Daily request limit reached for this demo. Please try again tomorrow.", int(history[0] + 86400 - now) + 1)
            if self._resumes_today + resume_count > settings.DAILY_RESUME_BUDGET:
                raise LimitExceeded(
                    "The demo has reached its daily processing budget. Please try again tomorrow.",
                    self._seconds_until_utc_midnight(),
                )

            history.append(now)
            self._resumes_today += resume_count

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
            self._budget_day = self._today()
            self._resumes_today = 0


limiter = DemoLimiter()
