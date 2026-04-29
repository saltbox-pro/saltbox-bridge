from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import logging
from typing import Any

from saltbox_bridge.exceptions import (
    CorePillarError,
    CorePillarTimeoutError,
)
from saltbox_bridge.utils.core_connector import CoreConnector
from saltbox_bridge_messages import BridgePillarDataRequest

# stub for static analyzers: __opts__ injected by salt loader at runtime
__opts__: dict[str, Any] = {}

LOGGER = logging.getLogger(__name__)


def __virtual__() -> bool | tuple[bool, str]:  # noqa: N807
    LOGGER.warning('Checking if core_pillar module can be loaded...')
    if __opts__['__role'] != 'master':
        return False, f'{__name__} runs on master only'
    return True


async def async_ext_pillar(minion_id: str, pillar: dict, *args: Any, **kwargs: Any) -> dict:
    opts = copy.deepcopy(__opts__)

    pillarenv: str = kwargs.get('pillarenv') or opts.get('pillarenv') or 'base'
    LOGGER.warning('Pillarenv: %s', pillarenv)

    if opts.get('pillarenv_from_saltenv', False) and 'saltenv' in opts and pillarenv == 'base':
        pillarenv = opts.get('saltenv', 'base')

    master_id = opts.get('salt_box_master_id')

    if not master_id or not isinstance(master_id, str):
        LOGGER.warning('salt_box_master_id is not set or invalid in __opts__, cannot retrieve pillar data from Core')
        return {}

    core_connector = CoreConnector(master_id=master_id)

    message = BridgePillarDataRequest(
        master=master_id,
        minion_id=minion_id,
        pillarenv=pillarenv,
    )
    try:
        response = await core_connector.send_message_and_wait_response(
            message_tag='get_pillar_data',
            message=message,
        )
        error_from_core = response.get('error')
        if error_from_core:
            msg = f'Error while retrieving pillar data for "{minion_id}/{master_id}/{pillarenv}": {error_from_core}'
            raise CorePillarError(msg) from None
        pillars: dict = response.get('pillars', {})
    except TimeoutError:
        msg = f'Timeout while waiting for pillar data response from Core for minion "{minion_id}" and env "{pillarenv}"'
        LOGGER.error(msg)
        raise CorePillarTimeoutError(msg) from None
    return pillars


def ext_pillar(minion_id: str, pillar: dict, *args: Any, **kwargs: Any) -> dict:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, async_ext_pillar(minion_id, pillar, *args, **kwargs))
        return future.result()
