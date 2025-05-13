from __future__ import annotations

import logging
import re
from typing import Any

from salt.utils import json

from saltbox_bridge.config import SETTINGS
from saltbox_bridge.event_bus.messages.minion_messages import GrainsOutMessage
from saltbox_bridge.exceptions import StopProcessing
from saltbox_bridge.salt_handlers.base_handler import BaseMessageHandler

LOGGER = logging.getLogger(__name__)


class JobReturnMessageHandler(BaseMessageHandler):
    """
    A message handler that handles salt job return messages
    """

    tag_pattern = re.compile(r'salt/job/(?P<jid>\d{20})/ret/(?P<mid>.+)')

    async def process(self, match: re.Match, data: dict[str, Any]) -> None:
        jid = match.group('jid')
        mid = match.group('mid')
        data['salt_master'] = self.salt_opts['salt_box_master_id']
        function = data['fun']
        data_json = json.dumps(data)

        LOGGER.info('Job %s return for %s, function %s', jid, mid, function)

        await self._process_return(jid=jid, mid=mid, function=function, data=data, data_json=data_json)

        raise StopProcessing()

    async def _process_return(self, jid: str, mid: str, function: str, data: dict, data_json: str):
        hash_name = f'job:{jid}:return'

        async with self.redis_client.pipeline(transaction=True) as pipe:
            pipe = pipe.hset(name=hash_name, key=mid, value=data_json)
            if SETTINGS.expire is not None:
                pipe = pipe.expire(name=hash_name, time=SETTINGS.expire)  # type: ignore
            await pipe.execute()

        await self.redis_client.publish(channel=hash_name, message=data_json)

        if function == 'grains.items':
            await self._process_grains(mid, data['return'])

    async def _process_grains(self, mid: str, grains: dict[str, Any]) -> None:
        LOGGER.debug('Processing grains for %s', mid)
        if not grains:
            return

        message = GrainsOutMessage(master=self.salt_opts['salt_box_master_id'], grains=grains)
        await self.send_message(message=message, message_tag='grains')


class JobReturnForTaskMessageHandler(JobReturnMessageHandler):
    """
    A message handler that handles salt job return messages for tasks
    """

    tag_pattern = re.compile(r'salt/job/(?P<jid>\d{20})-t(?P<tid>[a-zA-Z0-9]{24})/ret/(?P<mid>.+)')

    async def _process_task(self, jid, tid, data_json):
        await self.redis_client.publish(channel=f'task:{tid}:job:{jid}:return', message=data_json)

    async def process(self, match: re.Match, data: dict[str, Any]) -> None:
        jid = match.group('jid')
        tid = match.group('tid')
        mid = match.group('mid')

        data['jid'] = jid
        data['salt_master'] = self.salt_opts['salt_box_master_id']
        function = data['fun']
        data_json = json.dumps(data)

        LOGGER.info('Job %s (task %s) return for %s, function %s', jid, tid, mid, function)

        await self._process_return(jid=jid, mid=mid, function=function, data=data, data_json=data_json)
        await self._process_task(jid=jid, tid=tid, data_json=data_json)

        raise StopProcessing()
