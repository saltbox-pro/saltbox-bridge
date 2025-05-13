from __future__ import annotations

import logging
from typing import Annotated, Any

from faststream import Context
from faststream.redis import RedisRouter
from faststream.redis.message import RedisMessage

from saltbox_bridge.config import SETTINGS
from saltbox_bridge.event_bus.messages.sls_messages import ListSlsReposMessage
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.utils.salt_connector import SaltConnector, get_salt_caller, get_state_apply_error

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
    # TODO @: lock file
    # TODO @: Notify Salt.Box Core

    LOGGER.info('Start sync_repos')
    caller = get_salt_caller()
    repos = [r.dict() for r in message.repos]
    pillar = {
        'gitfs_repos': repos,
        'var_dir': str(SETTINGS.var_dir),
        'sshfs_server': SETTINGS.gitfs_server,
        'sshfs_port': SETTINGS.gitfs_port,
        'sshfs_sync_on': SETTINGS.sshfs_sync_on,
        'gitfs_privkey': str(SETTINGS.gitfs_privkey),
        'gitfs_pubkey': str(SETTINGS.gitfs_pubkey),
        'saltbox_env': 'saltbox',
    }
    ret = caller.cmd('state.apply', 'sync_repos', pillar=pillar)
    LOGGER.info('End sync_repos')
    if (errors := get_state_apply_error(ret)) is not None:
        for msg in errors:
            LOGGER.error(msg)
