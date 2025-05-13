from __future__ import annotations

import logging
from typing import Annotated, Any

from faststream import Context
from faststream.redis import RedisRouter
from faststream.redis.message import RedisMessage

from saltbox_bridge.event_bus.messages.pillar_messages import UpdatePillarCacheInMessage
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.utils.salt_connector import SaltConnector

LOGGER = logging.getLogger(__name__)
Message = Annotated[RedisMessage, Context()]


router = RedisRouter(middlewares=[MastersAuthMiddleware])
router_not_auth = RedisRouter()


@router.subscriber('update_pillar_cache')
async def update_pillar_cache(
    message: UpdatePillarCacheInMessage,
    salt_connector: SaltConnector = Context(),  # noqa: B008
) -> Any:
    return await salt_connector.update_pillar_cache(tgt=message.tgt, tgt_type=message.tgt_type)
