from __future__ import annotations

from typing import Any

import redis
from redis import asyncio as aioredis
from saltbox_bridge.config import SETTINGS

OPTS: dict[str, Any] = {
    'host': SETTINGS.redis_host,
    'port': SETTINGS.redis_port,
    'db': SETTINGS.redis_db,
    'username': SETTINGS.redis_username,
    'password': SETTINGS.redis_password,
    'ssl': SETTINGS.redis_ssl_use,
    'ssl_cert_reqs': SETTINGS.redis_ssl_cert_reqs,
    'ssl_ca_certs': SETTINGS.redis_ssl_ca_certs,
}


def get_sync_redis_client() -> redis.Redis:
    return redis.Redis(**OPTS)


def get_redis_client() -> aioredis.Redis:
    return aioredis.Redis(**OPTS)
