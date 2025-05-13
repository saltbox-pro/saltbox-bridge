from __future__ import annotations

import logging
from asyncio import sleep
from datetime import datetime, timedelta, timezone
from typing import Any

from faststream.redis import RedisBroker, RedisMessage

from saltbox_bridge.event_bus.faststream_redis import get_faststream_broker
from saltbox_bridge.event_bus.messages.base_messages import BaseMessage
from saltbox_bridge.event_bus.messages.system_messages import AuthMessage, MasterStatus, MasterStatusMessage
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.utils.gpg import SaltBoxCrypt

LOGGER = logging.getLogger(__name__)


class ConnectionsIsNotSuccessful(Exception):
    pass


class CoreConnector:
    def __init__(self, master_id: str, saltbox_crypt: SaltBoxCrypt):
        self.master_id: str = master_id
        self.saltbox_crypt: SaltBoxCrypt = saltbox_crypt
        self.master_status: MasterStatus = MasterStatus.new
        self.is_pubkey_set: bool = False
        self.is_connection_success: bool = False
        self.dt_last_check: datetime | None = None

    async def send_messagee(
        self,
        message: BaseMessage,
        message_tag: str,
        broker: RedisBroker | None = None,
        is_need_auth: bool = False,
    ) -> None:
        if not broker:
            if is_need_auth:
                broker = get_faststream_broker(middlewares=[MastersAuthMiddleware])
            else:
                broker = get_faststream_broker()

        async with broker as br:
            await br.publish(message=message, channel=f'master_{message_tag}')

    async def send_messge_and_wait_responce(
        self,
        message: BaseMessage,
        message_tag: str,
        response_timeout: float = 3.0,
        broker: RedisBroker | None = None,
        is_need_auth: bool = False,
    ) -> Any:
        if not broker:
            if is_need_auth:
                broker = get_faststream_broker(middlewares=[MastersAuthMiddleware])
            else:
                broker = get_faststream_broker()

        async with broker as br:
            response: RedisMessage = await br.request(  # type: ignore
                message,
                channel=f'master_{message_tag}',
                timeout=response_timeout,
            )
            return await response.decode() if response else None

    async def update_master_status(self) -> None:
        master_status: MasterStatusMessage = MasterStatusMessage(
            **await self.send_messge_and_wait_responce(
                message=BaseMessage(master=self.master_id), message_tag='status', is_need_auth=False
            )
        )

        LOGGER.info(master_status)

        self.master_status = master_status.status
        self.is_pubkey_set = master_status.is_pubkey_set

    async def auth_master(self) -> None:
        master_auth: AuthMessage = AuthMessage(
            **await self.send_messge_and_wait_responce(
                message=AuthMessage(master=self.master_id, pubkey=self.saltbox_crypt.pubkey),
                message_tag='auth',
                is_need_auth=False,
            )
        )

        if master_auth.pubkey:
            self.saltbox_crypt.save_pubkey_core(key_data=master_auth.pubkey)

        await self.update_master_status()

    async def check_connection(self, try_to_fix: bool = True, silent: bool = True) -> None:
        await self.update_master_status()
        self.is_connection_success = False

        try:
            if self.master_status != MasterStatus.accepted:
                msg = 'Master status is not accepted. Waiting...'
                raise ConnectionsIsNotSuccessful(msg)

            if not self.is_pubkey_set:
                if try_to_fix:
                    msg = 'Master pubkey is not set on core. Sending master pubkey to core and waiting...'
                    await self.auth_master()
                else:
                    msg = 'Master pubkey is not set on core. Waiting...'

                raise ConnectionsIsNotSuccessful(msg)

            if not self.saltbox_crypt.is_pubkey_core_exists:
                if try_to_fix:
                    msg = 'Core pubkey is not resieved on master. Sending auth request and waiting...'
                    await self.auth_master()
                else:
                    msg = 'Core pubkey is not resieved on master. Waiting...'

                raise ConnectionsIsNotSuccessful(msg)
        except ConnectionsIsNotSuccessful as e:
            self.dt_last_check = datetime.now(timezone.utc)

            if silent:
                LOGGER.warning(e)
                return None
            else:
                raise e

        self.dt_last_check = datetime.now(timezone.utc)
        self.is_connection_success = True
        return None

    async def wait_success_connection(self, try_to_fix: bool = True, ttl=900) -> None:
        dt_start_check: datetime = datetime.now(timezone.utc)

        LOGGER.info('Waiting for connection...')

        while not self.is_connection_success:
            if datetime.now(timezone.utc) - dt_start_check > timedelta(seconds=ttl):
                LOGGER.warning('Connection timed out. Waiting...')
                return None

            await self.check_connection(try_to_fix=try_to_fix)
            await sleep(10)

        LOGGER.info('Connection to core succeeded.')
        return None
