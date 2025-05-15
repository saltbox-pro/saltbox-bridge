from __future__ import annotations

import json
import logging
from typing import Any, cast

from salt.client import Caller, LocalClient
from salt.config import minion_config
from salt.exceptions import SaltException

from redis.asyncio import Redis
from saltbox_bridge.exceptions import CreateJobError
from saltbox_bridge.utils.types import SaltTgtType

LOGGER = logging.getLogger(__name__)


def get_salt_caller() -> Caller:
    opts = minion_config('/etc/salt/minion')
    opts['file_client'] = 'local'
    return Caller(mopts=opts)


def get_state_apply_error(data: list[str] | dict[str, dict[str, Any]]) -> list[str]:
    """
    Proccess return dict from salt state.apply function, return errors
    """
    # TODO: Search for standard salt function
    # TODO: Except potential errors while getting fileds
    if isinstance(data, list):
        return ['\n'.join(data)]
    elif isinstance(data, dict):
        errors = []
        for key, val in data.items():
            if not val['result']:
                comment = val.get('comment', 'COMMENT IS MISSING')
                errors.append(f'{key}: {comment}')
        return errors
    else:
        msg = f'Unexpected return type {type(data)}'  # type: ignore[unreachable]
        raise RuntimeError(msg)


class SaltConnector:
    def __init__(self, salt_opts: dict, redis_client: Redis) -> None:
        self.salt_opts = salt_opts
        self.redis_client = redis_client

    @property
    def salt_client(self) -> LocalClient:
        # Common case is to recreate the LocalClient before use. Keeping it leads to errors.
        # mopts takes preloaded master options to avoid re-reading configs.
        return LocalClient(c_path=None, mopts=self.salt_opts, auto_reconnect=True)  # type: ignore

    async def create_job_from_redis(self, hash_name: str) -> str:
        job_data: dict[bytes, bytes] = await self.redis_client.hgetall(hash_name)

        jid: str = job_data[b'jid'].decode()
        tgt: str = job_data[b'tgt'].decode()
        tgt_type: SaltTgtType = cast(SaltTgtType, job_data[b'tgt_type'].decode())
        fun: str = job_data[b'fun'].decode()
        arg: list = json.loads(job_data[b'arg']) if b'arg' in job_data else []
        kwarg: dict = json.loads(job_data[b'kwarg']) if b'kwarg' in job_data else {}
        status: str = job_data[b'status'].decode() if b'status' in job_data else None

        if status == 'processed':
            return jid

        try:
            back_jid: str = self.salt_client.cmd_async(
                tgt=tgt, tgt_type=tgt_type, fun=fun, arg=arg, kwarg=kwarg, jid=jid
            )
        except SaltException as err:
            LOGGER.exception(str(err))
            raise CreateJobError(str(err)) from err

        await self.redis_client.hset(hash_name, 'status', 'processed')
        await self.redis_client.expire(hash_name, 600)

        return back_jid

    async def create_all_jobs_from_redis(self) -> list[str]:
        hash_names = await self.redis_client.keys('job_create:*')
        jobs_jid: list[str] = []

        for hash_name in hash_names:
            try:
                jobs_jid.append(await self.create_job_from_redis(hash_name))
            except CreateJobError:
                continue

        return jobs_jid

    async def run_job_sync(
        self, tgt: str, tgt_type: SaltTgtType, fun: str, arg: list, kwarg: dict, jid: str | None
    ) -> dict[str, dict]:
        return self.salt_client.cmd(
            tgt=tgt, tgt_type=tgt_type, fun=fun, arg=arg, kwarg=kwarg, jid=jid, full_return=True
        )

    async def gather_minions(self, tgt: str, tgt_type: SaltTgtType) -> list[str]:
        return self.salt_client.gather_minions(tgt, tgt_type)

    async def update_pillar_cache(self, tgt: str, tgt_type: SaltTgtType) -> dict[str, dict]:
        return self.salt_client.cmd(tgt=tgt, tgt_type=tgt_type, fun='saltutil.refresh_pillar')
