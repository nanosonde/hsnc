"""In-memory fixed-window rate limiter for the login route.

A best-effort brute-force speed bump: it caps *failed* login attempts per client
key (IP) within a rolling window and blocks further attempts until the window
clears. Successful logins reset the counter.

State lives in process memory, so behind multiple gunicorn workers the effective
limit is per-worker. That is an intentional simplicity trade-off — a hardened
deployment should also sit behind a reverse proxy / WAF or use a shared-store
limiter — but it still meaningfully slows credential-stuffing against a single
node without adding a dependency.
"""

from __future__ import annotations

import threading
import time


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: float = 300.0) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        recent = [t for t in self._failures.get(key, []) if t >= cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, time.monotonic())) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            recent = self._prune(key, now)
            recent.append(now)
            self._failures[key] = recent

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
