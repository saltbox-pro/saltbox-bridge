from __future__ import annotations

import logging
from typing import Annotated

from faststream import Context
from faststream.redis import RedisRouter
from faststream.redis.message import RedisMessage

from saltbox_bridge.config import SETTINGS
from saltbox_bridge.event_bus.messages.minion_messages import GatherMinionsInMessage, GatherMinionsOutMessage, Minion
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.utils.salt_connector import SaltConnector

LOGGER = logging.getLogger(__name__)
Message = Annotated[RedisMessage, Context()]


router = RedisRouter(middlewares=[MastersAuthMiddleware])
router_not_auth = RedisRouter()


@router.subscriber('gather_minions')
async def gather_minions(
    message: GatherMinionsInMessage,
    salt_master: str = Context(),
    salt_connector: SaltConnector = Context(),  # noqa: B008
) -> GatherMinionsOutMessage:
    minions: list[str] = await salt_connector.gather_minions(tgt=message.tgt, tgt_type=message.tgt_type)

    result = GatherMinionsOutMessage(
        count=len(minions),
        minions=[
            Minion(minion_id=minion, master=salt_master) for minion in minions[: SETTINGS.max_count_of_gather_minions]
        ],
        master=salt_master,
    )

    return result
