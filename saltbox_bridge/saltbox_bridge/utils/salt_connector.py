from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from redis.asyncio import Redis
from salt.channel.client import ReqChannel  # type: ignore
from salt.client import LocalClient  # type: ignore
from salt.exceptions import SaltNoMinionsFound  # type: ignore
from salt.minion import SaltException  # type: ignore
from salt.utils.args import condition_input  # type: ignore
from salt.utils.minions import CkMinions  # type: ignore
from saltbox_bridge_messages import SaltTgtType

from saltbox_bridge.config import logger

T = TypeVar('T')


@dataclass
class JobResult(Generic[T]):
    value: T | None = None
    exc: SaltException | None = None


class SaltConnector:
    master_uri = 'tcp://localhost:4506'

    def __init__(self, salt_opts: dict, redis_client: Redis) -> None:
        self.salt_opts = salt_opts
        self.redis_client = redis_client

        with Path(self.salt_opts['cachedir']).joinpath('.root_key').open('r') as key_f:
            self.key = key_f.read()

        self.channel = ReqChannel.factory(self.salt_opts, crypt='clear', master_uri=self.master_uri)

    async def publish_job_via_zeromq(
        self, *, jid: str, tgt: str, tgt_type: SaltTgtType, fun: str, fun_args: list[Any], fun_kwargs: dict[Any, Any]
    ) -> JobResult[str]:
        load: dict[str, str | list | dict] = {
            'cmd': 'publish',
            'user': 'root',
            'key': self.key,
            'fun': fun,
            'tgt': tgt,
            'tgt_type': tgt_type,
            'arg': condition_input(fun_args, fun_kwargs),
            'ret': '',
            'jid': jid,
            'load': {},
        }
        if tgt_type == 'pillar':
            target_minions = await self.gather_minions(tgt=tgt, tgt_type=tgt_type)
            if not target_minions:
                msg = f'Failed to resolve minions for target: {tgt}'
                return JobResult(exc=SaltNoMinionsFound(msg))

            load['tgt_type'] = 'list'
            load['tgt'] = target_minions

        raw_ret = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.channel.send(load, timeout=60)
        )
        ret = raw_ret.get('load', {})
        ret_jid: str = ret.get('jid', '')
        logger.debug("Job return '%s' from ZeroMQ: %s", ret_jid, ret)

        if not ret_jid:
            msg = f'Failed to resolve minions for target: {load["tgt"]}'
            return JobResult(exc=SaltNoMinionsFound(msg))

        return JobResult(value=ret_jid)

    @property
    def salt_client(self) -> LocalClient:
        # Common case is to recreate the LocalClient before use. Keeping it leads to errors.
        # mopts takes preloaded master options to avoid re-reading configs.
        return LocalClient(c_path=None, mopts=self.salt_opts, auto_reconnect=True)

    async def gather_minions(self,
        tgt: str,
        tgt_type: SaltTgtType,
        greedy: bool = False
    ) -> Any | list[str]:
        result = CkMinions(self.salt_opts).check_minions(
            tgt,
            tgt_type=tgt_type,
            greedy=greedy
        )
        return result["minions"]

    async def update_pillar_cache(self, tgt: str, tgt_type: SaltTgtType) -> dict[str, dict] | Any:
        return self.salt_client.cmd(tgt=tgt, tgt_type=tgt_type, fun='saltutil.refresh_pillar')
