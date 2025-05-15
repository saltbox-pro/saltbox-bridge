from __future__ import annotations

import abc
import re
from typing import Any

from faststream.redis import RedisBroker
from salt.client import LocalClient

import redis.asyncio as redis
from saltbox_bridge.event_bus.messages.base_messages import BaseMessage


class BaseMessageHandler(abc.ABC):
    """
    A base class for handling salt.box messages

    Attributes:
        redis_client: Redis client
        salt_opts: Salt options
    """

    def __init__(self, redis_client: redis.Redis, broker: RedisBroker, salt_opts: dict) -> None:
        self.redis_client = redis_client
        self.broker = broker
        self.salt_opts = salt_opts

    @property
    def salt_client(self) -> LocalClient:
        return LocalClient(c_path=None, mopts=self.salt_opts, auto_reconnect=True)  # type: ignore

    async def send_message(self, message: BaseMessage, message_tag: str) -> None:
        async with self.broker as br:
            await br.publish(message=message, channel=f'master_{message_tag}')

    @property
    @abc.abstractmethod
    def tag_pattern(self) -> re.Pattern[str]: ...

    async def handle(self, tag: str, data: dict[str, Any]) -> None:
        """
        If tag matches tag_pattern, process message

        Args:
            tag: salt message tag
            data: salt message data

        Raises:
            StopProcessing: when no need to process the message with other handlers
        """
        if match := self.tag_pattern.match(tag):
            return await self.process(match, data)

        return None

    @abc.abstractmethod
    async def process(self, match: re.Match, data: dict[str, Any]) -> None:
        """
        Take action on message

        Args:
            match: matched salt message tag
            data: salt message data

        Raises:
            StopProcessing: when no need to process the message with other handlers
        """
