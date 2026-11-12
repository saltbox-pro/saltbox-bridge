from __future__ import annotations

import logging
from typing import Annotated, Any

from faststream import BaseMiddleware, Context
from faststream.broker.message import StreamMessage
from faststream.redis.message import RedisMessage
from faststream.types import AsyncFuncAny
from faststream.utils.context.repository import context
from saltbox_bridge_messages import BridgeMessageBase

LOGGER = logging.getLogger(__name__)
Message = Annotated[RedisMessage, Context()]


class MastersAuthMiddleware(BaseMiddleware):
    async def consume_scope(self, call_next: AsyncFuncAny, msg: StreamMessage[Any]) -> Any:
        try:
            message = BridgeMessageBase(**await msg.decode())  # type: ignore[arg-type]
        except Exception as e:
            error = f'Failed to decode message:\n{msg}\n{e}'
            LOGGER.error(error)
            return None

        salt_master: str = context.get('salt_master')

        if message.master and message.master != salt_master:
            LOGGER.error('Unknown master "%s"', message.master)
            return None

        return await super().consume_scope(call_next, msg)
