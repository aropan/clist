from __future__ import annotations

import asyncio
import inspect
import threading
import time
from collections import deque
from functools import wraps


class RateLimiter:
    """Thread-safe sliding-window limiter compatible with the old ratelimiter API."""

    def __init__(self, max_calls, period=1.0, callback=None):
        if period <= 0:
            raise ValueError("Rate limiting period should be > 0")
        if max_calls <= 0:
            raise ValueError("Rate limiting number of calls should be > 0")

        self.calls = deque()
        self.period = period
        self.max_calls = max_calls
        self.callback = callback
        self._lock = threading.Lock()
        self._async_lock = None
        self._async_lock_guard = threading.Lock()
        self._callback_tasks = set()

    def __call__(self, function):
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_wrapped(*args, **kwargs):
                async with self:
                    return await function(*args, **kwargs)

            return async_wrapped

        @wraps(function)
        def wrapped(*args, **kwargs):
            with self:
                return function(*args, **kwargs)

        return wrapped

    def __enter__(self):
        with self._lock:
            sleep_seconds = self._sleep_seconds()
            if sleep_seconds:
                self._notify_callback(sleep_seconds)
                time.sleep(sleep_seconds)
                self._discard_expired(time.monotonic())
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        with self._lock:
            now = time.monotonic()
            self.calls.append(now)
            self._discard_expired(now)

    async def __aenter__(self):
        if self._async_lock is None:
            with self._async_lock_guard:
                if self._async_lock is None:
                    self._async_lock = asyncio.Lock()

        async with self._async_lock:
            while True:
                with self._lock:
                    sleep_seconds = self._sleep_seconds()
                if not sleep_seconds:
                    break
                self._notify_async_callback(sleep_seconds)
                await asyncio.sleep(sleep_seconds)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.__exit__(exc_type, exc_value, traceback)

    def _sleep_seconds(self):
        now = time.monotonic()
        self._discard_expired(now)
        if len(self.calls) < self.max_calls:
            return 0
        return max(self.period - (now - self.calls[0]), 0)

    def _discard_expired(self, now):
        while self.calls and now - self.calls[0] >= self.period:
            self.calls.popleft()

    def _notify_callback(self, sleep_seconds):
        if self.callback is None:
            return
        until = time.time() + sleep_seconds
        thread = threading.Thread(target=self.callback, args=(until,), daemon=True)
        thread.start()

    def _notify_async_callback(self, sleep_seconds):
        if self.callback is None:
            return
        result = self.callback(time.time() + sleep_seconds)
        if inspect.isawaitable(result):
            task = asyncio.create_task(result)
            self._callback_tasks.add(task)
            task.add_done_callback(self._callback_tasks.discard)

    @property
    def _timespan(self):
        return self.calls[-1] - self.calls[0] if self.calls else 0
