from __future__ import annotations

import logging
import os
import ssl
from collections.abc import Callable
from typing import Any

from faststream import FastStream
from faststream.broker.types import BrokerMiddleware
from faststream.redis import RedisBroker, RedisRouter
from faststream.security import SASLPlaintext

from saltbox_bridge.config import SETTINGS, FaststreamRedisConf


def get_faststream_broker(
    redis_conf: FaststreamRedisConf | None = None,
    middlewares: list[BrokerMiddleware] | None = None,
    logger: logging.Logger | None = None,
) -> RedisBroker:
    if redis_conf is None:
        redis_conf = SETTINGS.faststream_redis_conf

    if redis_conf.url.startswith('rediss:'):
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
        ssl_context.verify_mode = {
            'none': ssl.CERT_NONE,
            'required': ssl.CERT_REQUIRED,
            'optional': ssl.CERT_OPTIONAL,
        }[redis_conf.ssl_cert_reqs]

        if redis_conf.ssl_ca_certs:
            ssl_context.load_verify_locations(cafile=os.path.relpath(redis_conf.ssl_ca_certs), capath=None, cadata=None)

        security = SASLPlaintext(username=redis_conf.username, password=redis_conf.password, ssl_context=ssl_context)
    else:
        security = SASLPlaintext(username=redis_conf.username, password=redis_conf.password)

    kwargs: dict[str, Any] = {
        'url': redis_conf.url,
        'security': security,
    }
    if middlewares:
        kwargs['middlewares'] = middlewares
    if logger:
        kwargs['logger'] = logger
    return RedisBroker(**kwargs)


def get_faststream_app(
    routers: list[RedisRouter],
    redis_conf: FaststreamRedisConf | None = None,
    middlewares: list[BrokerMiddleware] | None = None,
    broker: RedisBroker | None = None,
    logger: logging.Logger | None = None,
    lifespan: Callable | None = None,
) -> FastStream:
    if not broker:
        if not redis_conf:
            msg = 'Redis broker not configured'
            raise RuntimeError(msg)

        broker = get_faststream_broker(redis_conf=redis_conf, middlewares=middlewares, logger=logger)

    for router in routers:
        broker.include_router(router)

    kwargs: dict[str, Any] = {
        'broker': broker,
    }
    if lifespan:
        kwargs['lifespan'] = lifespan
    if logger:
        kwargs['logger'] = logger
    return FastStream(**kwargs)
