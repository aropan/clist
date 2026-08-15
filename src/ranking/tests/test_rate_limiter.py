import asyncio
from unittest.mock import patch

import pytest
from django.test import SimpleTestCase

from utils.ratelimiter import RateLimiter


class RateLimiterTest(SimpleTestCase):
    def test_decorator_waits_after_limit(self):
        limiter = RateLimiter(max_calls=1, period=60)

        @limiter
        def limited():
            return "ok"

        assert limited() == "ok"
        with patch("utils.ratelimiter.time.sleep") as sleep:
            assert limited() == "ok"

        sleep.assert_called_once()

    async def test_async_decorator(self):
        limiter = RateLimiter(max_calls=1, period=1)

        @limiter
        async def limited():
            await asyncio.sleep(0)
            return "ok"

        assert await limited() == "ok"
        assert len(limiter.calls) == 1

    def test_rejects_invalid_limits(self):
        with pytest.raises(ValueError, match="number of calls"):
            RateLimiter(max_calls=0)
        with pytest.raises(ValueError, match="period"):
            RateLimiter(max_calls=1, period=0)
