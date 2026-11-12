from __future__ import annotations

import logging
from asyncio import sleep
from datetime import datetime, timedelta
from typing import Any

from faststream.redis import RedisBroker
from saltbox_bridge_messages import (
    BridgeAuthRequest,
    BridgeMessageBase,
    CoreAuthResponse,
    MasterStatus,
    SshPubKeyModel,
)

from saltbox_bridge.config import HIERARHY
from saltbox_bridge.event_bus.faststream_redis import get_faststream_broker
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.exceptions import CoreConnectionTimeoutError
from saltbox_bridge.utils.system import utc_now

logger = logging.getLogger(__name__)


class CoreConnector:
    CONNECT_RETRY_INTERVAL_SEC = 10

    def __init__(self, master_id: str) -> None:
        self.master_id = master_id
        self.master_status = MasterStatus.NEW
        self.is_connected = False
        self.dt_last_check: datetime | None = None

    async def send_messagee(
        self,
        message: BridgeMessageBase,
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

    async def send_message_and_wait_response(
        self,
        message: BridgeMessageBase,
        message_tag: str,
        response_timeout: float = 3.0,
        broker: RedisBroker | None = None,
        is_need_auth: bool = False,
    ) -> Any:
        logger.debug('Sending message to Core: %s', message_tag)
        if not broker:
            if is_need_auth:
                broker = get_faststream_broker(middlewares=[MastersAuthMiddleware])
            else:
                broker = get_faststream_broker()

        async with broker as br:
            response = await br.request(
                message,
                channel=f'master_{message_tag}',
                timeout=response_timeout,
            )
            return await response.decode() if response else None

    def _make_auth_req_message(self) -> BridgeAuthRequest:
        sshfs_pubkey = HIERARHY.sshfs_pubkey.open().read().strip()
        salt_conf_pubkey = HIERARHY.salt_conf_pubkey.open().read().strip()
        return BridgeAuthRequest(
            master=self.master_id,
            salt_conf_pubkey=SshPubKeyModel.from_str(salt_conf_pubkey),
            sshfs_pubkey=SshPubKeyModel.from_str(sshfs_pubkey),
        )

    async def _connect(self) -> bool:
        try:
            ret = await self.send_message_and_wait_response(
                message=self._make_auth_req_message(),
                message_tag='auth',
                is_need_auth=False,
            )
        except TimeoutError:
            logger.error('Salt.Box Core did not respose on auth at a given time')
            return False
        master_auth = CoreAuthResponse(**ret)
        self.master_status = master_auth.status
        logger.info('Current Salt.Box status of master is %s', self.master_status)

        if self.master_status != MasterStatus.ACCEPTED:
            msg = 'Master status is not accepted. Waiting...'
            self.dt_last_check = utc_now()
            logger.warning(msg)
            return False

        self.dt_last_check = utc_now()
        return True

    async def wait_success_connection(self, timeout: int = 0) -> None:
        dt_start_check = utc_now()
        timeout_delta = timedelta(seconds=timeout)

        logger.info('Waiting for connection to Core...')

        while not self.is_connected:
            if timeout_delta and (utc_now() - dt_start_check > timeout_delta):
                msg = 'Connection to Core timed out, give up now'
                raise CoreConnectionTimeoutError(msg)

            self.is_connected = await self._connect()
            await sleep(self.CONNECT_RETRY_INTERVAL_SEC)

        logger.info('Connection to Core succeed')
