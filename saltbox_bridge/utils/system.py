from __future__ import annotations

import asyncio
import logging
import os
import random
import string
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def get_random_bytes(size: int) -> bytes:
    return os.urandom(size)


def get_random_string(size: int) -> str:
    return ''.join(random.choice(string.printable) for _ in range(size))  # ruff: ignore[suspicious-non-cryptographic-random-usage]


class SteadyRun:
    """
    Provides generator to iterate steadily for requested duration.
    """

    def __init__(self) -> None:
        self.counter = 0
        self.lagging_counter = 0

    async def run(self, duration: timedelta, rate: int, strict: bool = True) -> AsyncGenerator[datetime]:
        """
        :param duration: how long to send fake messages
        :param rate: target messages per second rate
        :param strict: exit on timeover if stict otherwise send all rate * duration messages
        :yield: current run time
        """
        def run_time_generator() -> Generator[tuple[datetime, datetime]]:
            current = start_time
            interval = timedelta(seconds=1 / rate)
            while current < end_time:
                next = current + interval
                yield current, next
                current = next

        self.counter = 0
        self.lagging_counter = 0

        if rate < 1:
            return

        start_time = utc_now()
        end_time = start_time + duration
        now = start_time

        for current, next in run_time_generator():
            yield current

            self.counter += 1
            now = utc_now()
            relax_time = (next - now).total_seconds()
            if relax_time < 0:
                self.lagging_counter += 1
            if strict and now > end_time:
                break
            await asyncio.sleep(relax_time)
        return
