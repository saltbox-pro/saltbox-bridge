from __future__ import annotations

import asyncio
import logging

from faststream import context
from salt.utils.event import get_master_event

from saltbox_bridge.config import SETTINGS
from saltbox_bridge.event_bus.core_connector import CoreConnector
from saltbox_bridge.event_bus.faststream_redis import get_faststream_broker
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.exceptions import CoreConnectionError, StopProcessing
from saltbox_bridge.redis import get_redis_client
from saltbox_bridge.salt_handlers.job_return_handler import (
    JobReturnForTaskMessageHandler,
    JobReturnMessageHandler,
)
from saltbox_bridge.salt_handlers.minion_started_handler import MinionStartedMessageHandler
from saltbox_bridge.salt_handlers.new_job_handler import JobNewForTaskMessageHandler, JobNewMessageHandler
from saltbox_bridge.salt_handlers.presence_handler import PresenceMessageHandler
from saltbox_bridge.utils.gpg import SaltBoxCrypt

LOGGER = logging.getLogger(__name__)


class SaltBridge:
    def __init__(
        self,
        salt_opts: dict,
    ) -> None:
        self.redis_client = get_redis_client()
        self.salt_opts = salt_opts

        self.broker = get_faststream_broker(
            redis_conf=SETTINGS.faststream_redis_conf, middlewares=[MastersAuthMiddleware]
        )
        handlers_args = {
            'redis_client': self.redis_client,
            'broker': self.broker,
            'salt_opts': self.salt_opts,
        }

        self.handlers = [
            JobNewMessageHandler(**handlers_args),
            JobNewForTaskMessageHandler(**handlers_args),
            JobReturnMessageHandler(**handlers_args),
            JobReturnForTaskMessageHandler(**handlers_args),
            PresenceMessageHandler(**handlers_args),
            MinionStartedMessageHandler(**handlers_args),
        ]

    async def start(self) -> None:
        master_id: str = self.salt_opts['salt_box_master_id']
        saltbox_crypt = SaltBoxCrypt(master_id=master_id, can_gen_new_key=False)
        core_connector = CoreConnector(master_id=master_id, saltbox_crypt=saltbox_crypt)

        context.set_global('saltbox_crypt', saltbox_crypt)
        context.set_global('core_connector', core_connector)
        context.set_global('master_id', master_id)

        await core_connector.wait_success_connection(try_to_fix=True, ttl=900)
        if not core_connector.is_connection_success:
            msg = 'Failed to connect to Core service'
            raise CoreConnectionError(msg)

        with get_master_event(self.salt_opts, self.salt_opts['sock_dir'], listen=True) as event_bus:
            while True:
                await self.process(event_bus.get_event(full=True))
                await asyncio.sleep(0.00001)

    async def process(self, event: dict | None) -> None:
        if not event:
            return

        tag = event['tag']
        data = event['data']

        LOGGER.debug('%s got event with tag "%s"', __name__, tag)

        for handler in self.handlers:
            try:
                await handler.handle(tag, data)
            except StopProcessing:
                LOGGER.debug('End message processing')
                return


async def _async_start(salt_opts: dict) -> None:
    salt_bridge = SaltBridge(salt_opts=salt_opts)
    await salt_bridge.start()


def start(
    salt_opts: dict,
) -> None:
    coro = _async_start(salt_opts=salt_opts)
    asyncio.run(coro)
