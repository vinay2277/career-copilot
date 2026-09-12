"""A small in-process rate limiter.

Written rather than pulled in because the behaviour needs to be exactly
predictable and unit-testable: this is what stands between a public URL and
someone spending the whole API budget in a loop.

Sliding window, not fixed: a fixed window lets a caller spend the full budget
in the last second of one window and again in the first second of the next,
which is twice the intended rate at precisely the wrong moment.

**Scope: one process.** Counters live in memory, so two workers each allow the
full budget and a restart clears everything. That is the right trade for a
single-instance deployment, which is what this app is. Running more than one
instance means moving the store to Redis — the interface here is narrow enough
that only `_Window` changes.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    #: Requests left in the current window.
    remaining: int
    #: Seconds until the caller may retry. 0 when allowed.
    retry_after: int
    limit: int


class SlidingWindowLimiter:
    """Allows `limit` events per `window_seconds`, per key.

    Thread-safe: FastAPI serves sync endpoints from a threadpool, so two
    requests genuinely do land here at once.
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.limit = limit
        self.window = float(window_seconds)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, now: float | None = None) -> Decision:
        """Record an attempt and decide whether it may proceed.

        A rejected attempt is deliberately *not* recorded. Counting rejections
        would let a caller who is already over the limit extend their own
        lockout indefinitely by continuing to hammer the endpoint.
        """
        now = time.monotonic() if now is None else now
        cutoff = now - self.window

        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= self.limit:
                retry_after = max(1, int(events[0] + self.window - now) + 1)
                return Decision(False, 0, retry_after, self.limit)

            events.append(now)
            return Decision(True, self.limit - len(events), 0, self.limit)

    def reset(self, key: str | None = None) -> None:
        """Clear one key, or all of them. For tests and for an admin unlock."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)

    def prune(self, *, now: float | None = None) -> int:
        """Drop keys with no recent events, returning how many were removed.

        Without this the key dictionary grows once per distinct client address
        and never shrinks — a slow leak on a public URL.
        """
        now = time.monotonic() if now is None else now
        cutoff = now - self.window

        with self._lock:
            stale = [
                key
                for key, events in self._events.items()
                if not events or events[-1] <= cutoff
            ]
            for key in stale:
                del self._events[key]
            return len(stale)
