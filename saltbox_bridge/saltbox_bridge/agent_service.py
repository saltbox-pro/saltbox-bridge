# Copyright 2025 Ivan Moshkov

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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import salt.config  # type: ignore[import-untyped]
from faststream import ContextRepo

from saltbox_bridge.config import SETTINGS, configure_logging
from saltbox_bridge.event_bus.faststream_redis import get_faststream_app
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.event_bus.router import router
from saltbox_bridge.redis import get_redis_client
from saltbox_bridge.utils.core_connector import CoreConnector
from saltbox_bridge.utils.salt_caller import SaltCaller
from saltbox_bridge.utils.salt_connector import SaltConnector

logger = logging.getLogger(__name__)


async def _async_start(salt_opts: dict | None) -> None:
    if salt_opts is None:
        salt_opts = salt.config.client_config('/etc/salt/master')
    configure_logging(format=f'{salt_opts["log_fmt_console"]} (Bridge Agent)')

    salt_master = salt_opts['salt_box_master_id']
    core_connector = CoreConnector(master_id=salt_master)
    salt_caller = SaltCaller(core_connector)

    await core_connector.wait_success_connection()

    @asynccontextmanager
    async def lifespan(context: ContextRepo) -> AsyncIterator:
        redis_client = get_redis_client()

        salt_connector = SaltConnector(salt_opts=salt_opts, redis_client=redis_client)

        context.set_global('redis_client', redis_client)
        context.set_global('salt_connector', salt_connector)
        context.set_global('salt_master', salt_master)
        context.set_global('salt_opts', salt_opts)
        context.set_global('core_connector', core_connector)
        context.set_global('salt_caller', salt_caller)

        yield

        del salt_connector
        del redis_client

    app = get_faststream_app(
        routers=[router],
        redis_conf=SETTINGS.faststream_redis_conf,
        lifespan=lifespan,
        logger=logging.getLogger(f'{__name__}.faststream'),
        middlewares=[MastersAuthMiddleware],
    )

    await salt_caller.sync_saltbox()
    await app.run(sleep_time=SETTINGS.faststream_app_sleep_time)


def start(
    salt_opts: dict | None = None,
) -> None:
    asyncio.run(_async_start(salt_opts=salt_opts))
