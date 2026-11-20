"""In-process limiter; each worker has its own independent counter."""

import asyncio
import time
from collections import defaultdict, deque

from app.core.config import settings


class RateLimitExceeded(Exception):
    pass


class InMemoryRateLimiter:
    def __init__(self, *, limit: int = 20, window_seconds: float = 60.0):
        if limit < 1 or window_seconds <= 0:
            raise ValueError("Rate limit and window must be positive.")
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        now = time.monotonic()
        async with self._lock:
            events = self._events[key]
            while events and now - events[0] >= self.window_seconds:
                events.popleft()
            if not events:
                self._events.pop(key, None)
                events = self._events[key]
            if len(events) >= self.limit:
                raise RateLimitExceeded
            events.append(now)
            if len(self._events) > 4096:
                cutoff = now - self.window_seconds
                for existing_key, existing_events in list(self._events.items()):
                    while existing_events and existing_events[0] < cutoff:
                        existing_events.popleft()
                    if not existing_events:
                        self._events.pop(existing_key, None)


rate_limiter = InMemoryRateLimiter(
    limit=settings.AI_RATE_LIMIT_REQUESTS,
    window_seconds=settings.AI_RATE_LIMIT_WINDOW_SECONDS,
)
