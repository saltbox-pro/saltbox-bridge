from __future__ import annotations

import logging
from typing import Annotated

from faststream import Context
from faststream.redis import RedisRouter
from faststream.redis.message import RedisMessage
from redis.asyncio import Redis
from saltbox_bridge_messages import (
    BridgeSyncDoneMessage,
    BridgeTestBurstLoadMessage,
    BridgeTestBurstResponse,
    BurstJobsTestReportSchema,
    CoreEmptyMessage,
    CoreTestBurstJobsRequest,
    CoreTestBurstRequest,
)

from saltbox_bridge.config import SETTINGS
from saltbox_bridge.event_bus.middlewares import MastersAuthMiddleware
from saltbox_bridge.utils.core_connector import CoreConnector
from saltbox_bridge.utils.salt_bus import FakeJobNewEventGenerator
from saltbox_bridge.utils.salt_caller import SaltCaller
from saltbox_bridge.utils.system import get_random_string, utc_now

BURST_JOBS_TEST_REPORT_HASH_NAME = 'burst_jobs_test'
Message = Annotated[RedisMessage, Context()]

logger = logging.getLogger(__name__)
router = RedisRouter(middlewares=[MastersAuthMiddleware])
router_not_auth = RedisRouter()


@router.subscriber('sync_saltbox')
async def sync_saltbox(
    message: CoreEmptyMessage,
    salt_caller: SaltCaller = Context(),  # ruff: ignore[function-call-in-default-argument]
) -> None:
    await salt_caller.sync_saltbox()


@router.subscriber('sync_templates')
async def sync_templates(
    message: CoreEmptyMessage,
    salt_caller: SaltCaller = Context(),  # ruff: ignore[function-call-in-default-argument]
) -> BridgeSyncDoneMessage:
    return await salt_caller.sync_templates()


@router.subscriber('burst_test')
async def burst_test(
    message: CoreTestBurstRequest,
    core_connector: CoreConnector = Context(),  # ruff: ignore[function-call-in-default-argument]
) -> BridgeTestBurstResponse:
    load = get_random_string(message.size)
    start = utc_now()
    for _ in range(message.count):
        load_msg = BridgeTestBurstLoadMessage(master=message.master, load=load)
        await core_connector.send_messagee(message=load_msg, message_tag='burst_test_load')
    duration = utc_now() - start
    return BridgeTestBurstResponse(master=message.master, time=duration)


@router.subscriber('burst_jobs_test')
async def burst_jobs_test(
    message: CoreTestBurstJobsRequest,
    redis_client: Redis = Context(),  # ruff: ignore[function-call-in-default-argument]
) -> None:
    gen = FakeJobNewEventGenerator()
    start = utc_now()
    sent, overdue = await gen.fire(
        id=message.id,
        duration=message.duration,
        rate=message.rate,
        strict=message.strict,
    )
    end = utc_now()
    logger.info('Sent %d fake job/{jid}/new messages, sent with delay: %d', sent, overdue)

    report = BurstJobsTestReportSchema(
        count=sent,
        overdue=overdue,
        start=start,
        end=end,
    )

    async with redis_client.pipeline() as pipe:
        pipe.hset(name=BURST_JOBS_TEST_REPORT_HASH_NAME, key=message.id, value=report.model_dump_json())
        if SETTINGS.expire is not None:
            pipe = pipe.hexpire(  # type: ignore[attr-defined]
                BURST_JOBS_TEST_REPORT_HASH_NAME, SETTINGS.expire, message.id
            )
        await pipe.execute()


@router.subscriber('ping')
async def ping(
    message: CoreEmptyMessage,
    salt_caller: SaltCaller = Context(),  # ruff: ignore[function-call-in-default-argument]
) -> BridgeSyncDoneMessage:
    logger.debug('Received ping message from master %s', message.master)
    return await salt_caller.ping()
