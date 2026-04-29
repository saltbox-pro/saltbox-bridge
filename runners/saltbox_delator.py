"""
FastMS engines.saltbox_delator related functions
"""

import logging
from datetime import datetime, timedelta, timezone

from redis import ConnectionError
from salt.exceptions import CommandExecutionError  # type: ignore
from saltbox_bridge.config import SETTINGS
from saltbox_bridge.redis import get_sync_redis_client

LOGGER = logging.getLogger(__name__)


def __virtual__() -> bool:  # noqa: N807
    return True


def cleanup_expired_jobs() -> int:
    """
    Cleanup expired records in jobs sorted set and return amount of deletions
    """
    if SETTINGS.expire is None:
        LOGGER.info('Expiration is disabled with expire option, nothing to do')
        return 0

    redis_client = get_sync_redis_client()
    expiration_time = (datetime.now(tz=timezone.utc) - timedelta(seconds=SETTINGS.expire)).timestamp()
    try:
        LOGGER.info('Running expired job records cleanup')
        deleted_jobs_num = redis_client.zremrangebyscore('jobs', min=0.0, max=expiration_time)
        LOGGER.info('%i expired job records deleted', deleted_jobs_num)
        return deleted_jobs_num
    except ConnectionError as err:
        raise CommandExecutionError(err) from err
