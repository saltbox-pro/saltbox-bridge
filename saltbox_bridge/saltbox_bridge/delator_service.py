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
import logging
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any  # type: ignore

import orjson  # type: ignore
import salt.config  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from redis import exceptions as redis_exceptions
from salt.utils.event import get_master_event  # type: ignore[import-untyped]

from saltbox_bridge.config import configure_logging
from saltbox_bridge.redis import get_redis_client
from saltbox_bridge.utils.core_connector import CoreConnector

LOGGER = logging.getLogger(__name__)


class SaltBridge:
    def __init__(
        self,
        salt_opts: dict,
    ) -> None:
        self.redis_client = get_redis_client()
        self.salt_opts = salt_opts
        self.master_id: str = self.salt_opts['salt_box_master_id']
        self.core_connector = CoreConnector(master_id=self.master_id)
        self.local_buffer: list[dict] = []
        self.sem = asyncio.Semaphore(10)

    async def start(self) -> None:
        await self.core_connector.wait_success_connection()

        with get_master_event(self.salt_opts, self.salt_opts['sock_dir'], listen=True) as event_bus:
            while True:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: event_bus.get_event(full=True, no_block=False, wait=5)
                )
                if event is None:
                    await asyncio.sleep(0.01)
                    continue
                await self.process(event)

    async def _send_from_local_buffer(self) -> None:
        if not self.local_buffer:
            return

        async def worker(event: dict):
            async with self.sem:
                await self._send_to_events_buffer(tag=event['tag'], data=event['data'])
        workers: list[Coroutine] = [worker(event) for event in self.local_buffer]
        await asyncio.gather(*workers)

    async def _send_to_events_buffer(self, tag: str, data: dict[str, Any]) -> None:
        try:
            await self.redis_client.rpush(
                f'salt-events:{self.master_id}:to_process',
                orjson.dumps({'master_id': self.master_id, 'tag': tag, 'data': data}),
            )
        except redis_exceptions.RedisError:
            LOGGER.exception('Redis error')
            self.local_buffer.append({'tag': tag, 'data': data})

    async def process(self, event: dict | None) -> None:
        if not event:
            return

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
