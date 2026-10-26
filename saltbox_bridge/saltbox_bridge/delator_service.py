# Copyright 2025 Anton Karmanov, Ivan Moshkov

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import salt.config  # type: ignore[import-untyped]
from redis import exceptions as redis_exceptions
from salt.utils.event import get_master_event  # type: ignore[import-untyped]

from saltbox_bridge.config import SETTINGS, configure_logging
from saltbox_bridge.redis import get_redis_client
from saltbox_bridge.utils.core_connector import CoreConnector

LOGGER = logging.getLogger(__name__)


class SaltBridge:
    def __init__(self, salt_opts: dict) -> None:
        self.redis_client = get_redis_client()
        self.salt_opts = salt_opts
        self.master_id: str = self.salt_opts['salt_box_master_id']
        self.core_connector = CoreConnector(master_id=self.master_id)
        self.local_buffer: list[dict] = []
        self.background_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:

        with get_master_event(self.salt_opts, self.salt_opts['sock_dir'], listen=True) as event_bus:

            connection_task = asyncio.create_task(self.core_connector.wait_success_connection())

            while True:
                event = await asyncio.get_event_loop().run_in_executor(
                    event_bus.io_loop,
                    lambda: event_bus.get_event(full=True, no_block=False, wait=SETTINGS.delator_wait_time),
                )

                is_core_connected = self._is_core_connected(connection_task)

                if is_core_connected and self.local_buffer:
                    await self._send_from_local_buffer()

                if not event:
                    continue

                if not is_core_connected:
                    tag = event['tag']
                    msg = f'Core is not connected yet, keep event with tag {tag!r} in local_buffer'
                    LOGGER.debug(msg)
                    self.local_buffer.append({'tag': event['tag'], 'data': event['data']})
                    continue

                task = asyncio.create_task(self.process(event))
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)

    @staticmethod
    def _is_core_connected(connection_task: asyncio.Task) -> bool:
        if not connection_task.done():
            return False

        connection_task.result()
        return True

    async def _send_from_local_buffer(self) -> None:
        buffered_events = self.local_buffer
        self.local_buffer = []

        for event in buffered_events:
            await self._send_to_events_buffer(tag=event['tag'], data=event['data'])

    async def _send_to_events_buffer(self, tag: str, data: dict[str, Any]) -> None:
        try:
            await self.redis_client.rpush(
                f'salt-events:{self.master_id}:to_process',
                json.dumps({'master_id': self.master_id, 'tag': tag, 'data': data}),
            )
        except redis_exceptions.RedisError:
            LOGGER.exception('Redis error')
            self.local_buffer.append({'tag': tag, 'data': data})

    async def process(self, event: dict) -> None:
        tag = event['tag']
        data = event['data']

        LOGGER.debug('%s got event with tag "%s"', __name__, tag)

        await self._send_from_local_buffer()
        await self._send_to_events_buffer(tag, data)


async def _async_start(salt_opts: dict | None) -> None:
    if salt_opts is None:
        salt_opts = salt.config.client_config('/etc/salt/master')
    configure_logging(format=f'{salt_opts["log_fmt_console"]} (Bridge Delator)')
    salt_bridge = SaltBridge(salt_opts=salt_opts)
    await salt_bridge.start()


def start(salt_opts: dict | None = None) -> None:
    coro = _async_start(salt_opts=salt_opts)
    asyncio.run(coro)
