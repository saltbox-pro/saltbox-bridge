from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

from salt.utils.dictupdate import merge  # type: ignore[import-untyped]
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
    """
    Retrieve pillar data for a given minion from the SaltBox core service.

    This function sends a request to the core service to get pillar data for the specified minion and pillar
    environment(s). It then merges the received pillar data according to the configured merging strategy and
    returns the final result.

    Args:
        minion_id (str): The ID of the minion for which to retrieve pillar data.
        pillar (dict): The existing pillar data (can be used as a base for merging).
        *args: Additional positional arguments (not used in this implementation).
        **kwargs: Additional keyword arguments that can include:
            - pillarenv (str): The pillar environment(s) to use (comma-separated if multiple).
            - Other options from __opts__ that can influence the behavior of this function.
    Returns:
        dict: The merged pillar data for the specified minion and environment(s).
    """

    opts = copy.deepcopy(__opts__)

    pillarenv: str = kwargs.get('pillarenv') or opts.get('pillarenv') or 'base'

    if opts.get('pillarenv_from_saltenv', False) and 'saltenv' in opts and pillarenv == 'base':
        pillarenv = opts.get('saltenv', 'base')

    envs = [e.strip() for e in pillarenv.split(',') if e.strip()]

    result: dict = {}
    strategy = opts.get('pillar_source_merging_strategy', 'smart')
    renderer = opts.get('renderer', 'yaml')
    merge_lists = opts.get('pillar_merge_lists', False)
    master_id = opts.get('salt_box_master_id')

    if not master_id or not isinstance(master_id, str):
        return result

    core_connector = CoreConnector(master_id=master_id)

    for env in envs:
        message = BridgePillarDataRequest(
            master=master_id,
            minion_id=minion_id,
            pillarenv=env,
        )
        try:
            response = await core_connector.send_message_and_wait_response(
                message_tag='get_pillar_data',
                message=message,
            )
        except TimeoutError:
            msg = f'Timeout while waiting for pillar data response from Core for minion "{minion_id}" and env "{env}"'
            LOGGER.error(msg)
            raise CorePillarTimeoutError(msg) from None

        error_from_core = response.get('error')
        if error_from_core:
            msg = f'Error while retrieving pillar data for "{minion_id}/{master_id}/{env}": {error_from_core}'
            raise CorePillarError(msg) from None

        pillars: dict = response.get('pillars', {})
        result = merge(result, pillars, strategy, renderer, merge_lists)

    return result


def ext_pillar(minion_id: str, pillar: dict, *args: Any, **kwargs: Any) -> dict:
    return asyncio.run(async_ext_pillar(minion_id, pillar, *args, **kwargs))
