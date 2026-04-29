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
from typing import Any

import orjson
import salt.config  # type: ignore[import-untyped]
from salt.exceptions import SaltNoMinionsFound  # type: ignore

from saltbox_bridge.config import SETTINGS, configure_logging
from saltbox_bridge.redis import get_redis_client
from saltbox_bridge.utils.core_connector import CoreConnector
from saltbox_bridge.utils.salt_connector import JobResult, SaltConnector

LOGGER = logging.getLogger(__name__)


class JobRunner:
    JOBS_TO_CREATE_SET_NAME_PATTERN = 'jobs:{master_id}:to_create'

    def __init__(
        self,
        salt_opts: dict,
    ) -> None:
        self.redis_client = get_redis_client()
        self.salt_opts = salt_opts
        self.master_id: str = self.salt_opts['salt_box_master_id']
        self.core_connector = CoreConnector(master_id=self.master_id)
        self.salt_connector = SaltConnector(salt_opts=salt_opts, redis_client=self.redis_client)
        self.jobs_to_create_list_name = self.JOBS_TO_CREATE_SET_NAME_PATTERN.format(master_id=self.master_id)
        self.background_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        await self.core_connector.wait_success_connection()

        while True:
            raw: tuple[Any, Any] | None = await self.redis_client.blpop(
                self.jobs_to_create_list_name, SETTINGS.runner_batch_size
            )
            if raw is None:
                continue

            _, raw_job_data = raw
            job_data = orjson.loads(raw_job_data.decode())
            task = asyncio.create_task(self.process(job_data))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

    async def process(self, job_data: dict[str, Any]) -> None:
        result: JobResult[str] = await self.salt_connector.publish_job_via_zeromq(
            jid=job_data['jid'],
            tgt=job_data['tgt'],
            tgt_type=job_data['tgt_type'],
            fun=job_data['fun'],
            fun_args=job_data.get('arg', []) or [],
            fun_kwargs=job_data.get('kwarg', {}) or {},
        )

        if result.exc:
            job_data.setdefault('retries', 0)
            job_data['retries'] += 1

            if job_data['retries'] > SETTINGS.runner_max_retries_to_run_job:
                error_type: str = 'unknown'

                if isinstance(result.exc, SaltNoMinionsFound):
                    error_type = 'no_minions_found'

                await self.redis_client.rpush(
                    f'salt-events:{self.master_id}:to_process',
                    orjson.dumps(
                        {
                            'master_id': self.master_id,
                            'tag': f'saltbox/job/{job_data["jid"]}/error',
                            'data': {'error_type': error_type},
                        }
                    ),
                )

                LOGGER.debug('Job reached max retries, skipping job: %s', job_data)
                return

            await self.redis_client.lpush(self.jobs_to_create_list_name, orjson.dumps(job_data))


async def _async_start(salt_opts: dict | None) -> None:
    if salt_opts is None:
        salt_opts = salt.config.client_config('/etc/salt/master')
    configure_logging(format=f'{salt_opts["log_fmt_console"]} (Bridge Job Runner)')
    job_runner = JobRunner(salt_opts=salt_opts)
    await job_runner.start()


def start(salt_opts: dict | None = None) -> None:
    coro = _async_start(salt_opts=salt_opts)
    asyncio.run(coro)
