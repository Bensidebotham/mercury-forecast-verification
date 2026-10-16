"""Shared HTTP plumbing for the API clients: one User-Agent, retries, pacing."""
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from weather_vs_market import USER_AGENT


@contextmanager
def session(client: httpx.Client | None, timeout: float = 30) -> Iterator[httpx.Client]:
    """Use the caller's client, or open (and close) a short-lived one."""
    if client is not None:
        yield client
        return
    with httpx.Client(timeout=timeout) as own:
        yield own


class Pacer:
    """Keeps at least `min_interval_s` between requests (per host, per process).

    Thread-safe: worker threads share one budget, so concurrency hides latency
    without exceeding the host's rate limit.
    """

    def __init__(self, min_interval_s: float):
        self.min_interval_s = min_interval_s
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.min_interval_s
        if slot > now:
            time.sleep(slot - now)


def get(client: httpx.Client, url: str, params=None, *, pacer: Pacer | None = None,
        max_tries: int = 5, backoff_s: float = 1.0) -> httpx.Response:
    """GET with exponential backoff on 429, 5xx and transport errors; other 4xx raise at once."""
    for attempt in range(max_tries):
        if pacer:
            pacer.wait()
        last = attempt == max_tries - 1
        try:
            resp = client.get(url, params=params, headers=USER_AGENT)
        except httpx.TransportError:
            if last:
                raise
            time.sleep(backoff_s * 2**attempt)
            continue
        if (resp.status_code == 429 or resp.status_code >= 500) and not last:
            time.sleep(backoff_s * 2**attempt)
            continue
        resp.raise_for_status()
        return resp
    raise AssertionError("unreachable")
