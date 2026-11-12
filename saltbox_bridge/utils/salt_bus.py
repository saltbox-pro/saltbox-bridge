from __future__ import annotations

import abc
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, ClassVar

from salt.config import master_config  # type: ignore[import-untyped]
from salt.utils.event import MasterEvent, get_master_event  # type: ignore[import-untyped]

from saltbox_bridge.utils.system import SteadyRun, utc_now

logger = logging.getLogger(__name__)

MASTER_CONF_PATH = '/etc/salt/master'


class SaltBusMessage(abc.ABC):
    @abc.abstractmethod
    def get_tag(self) -> str: ...
    @abc.abstractmethod
    def get_data(self) -> dict[str, Any]: ...


class FakeJobNewBusMessage(SaltBusMessage):
    LATEST_JID_TIME = utc_now()
    DEFAULT_MINIONS: ClassVar = ['fake!_minion']

    def __init__(self,
        label: str,
        fun: str = 'test.ping',
        minions: list[str] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.minions = minions if minions is not None else self.DEFAULT_MINIONS
        self.jid = self._gen_jid(created_at)
        self.fun = fun
        self.label = label

    def get_tag(self) -> str:
        return f'salt/job/{self.jid}/new'

    def get_data(self) -> dict[str, Any]:
        return {
            '_fake_message_label': self.label,
            'arg': [],
            'fun': self.fun,
            'jid': self.jid,
            'minions': self.minions,
            'missing': [],
            'tgt': self.minions,
            'tgt_type': 'list',
            'user': 'root'
        }

    def _gen_jid(self, timestamp: datetime | None = None) -> str:
        if timestamp is None:
            timestamp = utc_now()
        if timestamp <= self.LATEST_JID_TIME:
            timestamp = self.LATEST_JID_TIME + timedelta(microseconds=1)
        self.LATEST_JID_TIME = timestamp
        return f'{timestamp:%Y%m%d%H%M%S%f}'


def get_event_obj() -> MasterEvent:
    opts = master_config(MASTER_CONF_PATH)
    return get_master_event(opts, sock_dir=opts['sock_dir'], listen=False)


class FakeJobNewEventGenerator:
    lock = asyncio.Lock()

    async def fire(self, id: str, duration: timedelta, rate: int, strict: bool = True) -> tuple[int, int]:
        """
        Generate fake `job/{jid}/new` messages

        :param id: unique identifier for the burst
        :param duration: how long to send fake messages
        :param rate: target messages per second rate
        :param strict: exit on timeover if stict otherwise send all rate * duration messages
        :return: counters of all sent messages and sent with delay messages
        """
        sent_counter = 0
        lagging_counter = 0

        if rate < 1:
            return sent_counter, lagging_counter

        async with self.lock:
            event = get_event_obj()
            runner = SteadyRun()

            async for now in runner.run(duration=duration, rate=rate, strict=strict):
                data = FakeJobNewBusMessage(label=id, created_at=now)
                event.fire_event(data=data.get_data(), tag=data.get_tag())
        return runner.counter, runner.lagging_counter
