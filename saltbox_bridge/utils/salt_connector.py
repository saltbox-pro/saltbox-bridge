from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any, Generic, TypeVar

from redis.asyncio import Redis
from salt.channel.client import ReqChannel  # type: ignore
from salt.client import LocalClient  # type: ignore
from salt.exceptions import SaltNoMinionsFound  # type: ignore
from salt.key import Key  # type: ignore
from salt.minion import SaltException  # type: ignore
from salt.utils.args import condition_input  # type: ignore
from salt.utils.minions import CkMinions  # type: ignore
from saltbox_bridge_messages import SaltKeyStatusType, SaltTgtType

LOGGER = logging.getLogger(__name__)


T = TypeVar('T')

SALT_KEY_ACCEPTED = 'minions'
SALT_KEY_UNACCEPTED = 'minions_pre'
SALT_KEY_REJECTED = 'minions_rejected'
SALT_KET_DENIED = 'minions_denied'

SALT_KEY_TYPES_MAP = {
    SaltKeyStatusType.accepted: SALT_KEY_ACCEPTED,
    SaltKeyStatusType.unaccepted: SALT_KEY_UNACCEPTED,
    SaltKeyStatusType.rejected: SALT_KEY_REJECTED,
    SaltKeyStatusType.denied: SALT_KET_DENIED,
}


@dataclass
class JobResult(Generic[T]):
    value: T | None = None
    exc: SaltException | None = None


class SaltConnector:
    CHANNEL_TIMEOUT = time(second=59)

    def __init__(self, salt_opts: dict, redis_client: Redis) -> None:
        self.salt_opts = salt_opts
        self.redis_client = redis_client

        with Path(self.salt_opts['cachedir']).joinpath('.root_key').open('r') as key_f:
            self.key = key_f.read()

        self.master_port = salt_opts.get('ret_port', '4506')
        self.master_uri = f'tcp://localhost:{self.master_port}'
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

        raw_ret = self.channel.send(load, timeout=self.CHANNEL_TIMEOUT.second)
        ret = raw_ret.get('load', {})
        ret_jid: str = ret.get('jid', '')
        if not ret_jid:
            msg = f'Failed to resolve minions for target: {load["tgt"]}'
            return JobResult(exc=SaltNoMinionsFound(msg))

        return JobResult(value=ret_jid)

    @property
    def salt_client(self) -> LocalClient:
        # Common case is to recreate the LocalClient before use. Keeping it leads to errors.
        # mopts takes preloaded master options to avoid re-reading configs.
        return LocalClient(c_path=None, mopts=self.salt_opts, auto_reconnect=True)

    @property
    def salt_key_manager(self) -> Key:
        return Key(self.salt_opts)

    async def gather_minions(self, tgt: str, tgt_type: SaltTgtType, greedy: bool = False) -> Any | list[str]:
        result = CkMinions(self.salt_opts).check_minions(tgt, tgt_type=tgt_type, greedy=greedy)
        return result.get('minions', [])

    async def update_pillar_cache(self, tgt: str, tgt_type: SaltTgtType) -> dict[str, dict] | Any:
        return self.salt_client.cmd(tgt=tgt, tgt_type=tgt_type, fun='saltutil.refresh_pillar')

    async def salt_key_accept(self, minions_ids: list[str]) -> list[str]:
        raw_result: dict[str, list[str]] = self.salt_key_manager.accept(
            match=','.join(minions_ids), include_denied=True, include_rejected=True
        )

        return raw_result.get(SALT_KEY_ACCEPTED, [])

    async def salt_key_all_accept(self) -> list[str]:
        raw_result: dict[str, list[str]] = self.salt_key_manager.accept_all()

        return raw_result.get(SALT_KEY_ACCEPTED, [])

    async def salt_key_reject(self, minions_ids: list[str]) -> list[str]:
        raw_result: dict[str, list[str]] = self.salt_key_manager.reject(
            match=','.join(minions_ids), include_denied=True, include_accepted=True
        )

        return raw_result.get(SALT_KEY_REJECTED, [])

    async def salt_key_all_reject(self) -> list[str]:
        raw_result: dict[str, list[str]] = self.salt_key_manager.reject_all()

        return raw_result.get(SALT_KEY_REJECTED, [])

    async def salt_key_delete(self, minions_ids: list[str]) -> None:
        self.salt_key_manager.delete_key(match=','.join(minions_ids))

    async def salt_key_all_delete(self) -> None:
        self.salt_key_manager.delete_all()

    async def get_salt_keys_list(self, status: SaltKeyStatusType | None = None) -> dict[SaltKeyStatusType, list[str]]:
        raw_result: dict[str, list[str]] = self.salt_key_manager.list_keys()
        salt_keys: dict[SaltKeyStatusType, list[str]] = {}

        if status is None:
            for key_type, raw_type in SALT_KEY_TYPES_MAP.items():
                salt_keys[key_type] = raw_result.get(raw_type, [])
        else:
            salt_keys[status] = raw_result.get(SALT_KEY_TYPES_MAP[status], [])

        return salt_keys
