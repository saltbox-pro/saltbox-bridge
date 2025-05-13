from __future__ import annotations

import logging
from typing import Annotated, Any

from faststream import Context
from faststream.redis import RedisRouter
from faststream.redis.message import RedisMessage

from saltbox_bridge.event_bus.messages.sls_messages import ListSlsReposMessage
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.utils.salt_connector import SaltConnector, get_salt_caller

LOGGER = logging.getLogger(__name__)
Message = Annotated[RedisMessage, Context()]

router = RedisRouter(middlewares=[MastersAuthMiddleware])
router_not_auth = RedisRouter()


@router.subscriber('sync_repos')
async def sync_repos(
    message: ListSlsReposMessage,
    salt_connector: SaltConnector = Context(),  # noqa: B008
) -> Any:
    # TODO @: True async?
    # TODO @: Setup gitfs
    # TODO @: rsync files
    # TODO @: lock file
    # TODO @: Notify Salt.Box Core

    caller = get_salt_caller()
    repos = [r.model_dump() for r in message.repos]
    _ret = caller.cmd('state.apply', 'sync_repos', out='yaml', pillar={'gitfs_repos': repos})
