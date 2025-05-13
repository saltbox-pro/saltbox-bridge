from __future__ import annotations

import logging
from typing import Annotated

from faststream import Context, Logger
from faststream.redis import RedisRouter
from faststream.redis.message import RedisMessage

from saltbox_bridge.event_bus.messages.job_messages import (
    JobReturn,
    JobSyncOutMessage,
    NewJobIneMessage,
    NewJobSyncIneMessage,
)
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.exceptions import CreateJobError
from saltbox_bridge.utils.salt_connector import SaltConnector

LOGGER = logging.getLogger(__name__)
Message = Annotated[RedisMessage, Context()]


router = RedisRouter(middlewares=[MastersAuthMiddleware])
router_not_auth = RedisRouter()


@router.subscriber('run_job')
async def run_job(
    message: NewJobIneMessage,
    logger: Logger,
    salt_connector: SaltConnector = Context(),  # noqa: B008
) -> str | None:
    try:
        jid: str = await salt_connector.create_job_from_redis(
            hash_name=message.hash_name,
        )
        logger.info('Created job: %s', jid)
        return jid
    except CreateJobError as error:
        logger.error(error)
        return None


@router.subscriber('run_job_sync')
async def run_job_sync(
    message: NewJobSyncIneMessage,
    logger: Logger,
    salt_connector: SaltConnector = Context(),  # noqa: B008
) -> JobSyncOutMessage | None:
    try:
        job_result: dict = await salt_connector.run_job_sync(
            tgt=message.tgt,
            tgt_type=message.tgt_type,
            fun=message.fun,
            arg=message.arg,
            kwarg=message.kwarg,
            jid=message.jid,
        )

        jid: str = next(iter(job_result.values()), {}).get('jid', '')

        result = JobSyncOutMessage(
            **message.model_dump(exclude={'jid'}),
            jid=jid,
            returns={minion_id: JobReturn(**job_return) for minion_id, job_return in job_result.items()},
        )

        logger.info('Created job: %s', result)
        return result
    except CreateJobError as error:
        logger.error(error)
        return None
