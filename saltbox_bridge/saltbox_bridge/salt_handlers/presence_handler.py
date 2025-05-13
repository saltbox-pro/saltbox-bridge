from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from saltbox_bridge.event_bus.messages.minion_messages import PresenceMessage
from saltbox_bridge.exceptions import StopProcessing
from saltbox_bridge.salt_handlers.base_handler import BaseMessageHandler


class PresenceMessageHandler(BaseMessageHandler):
    """
    A message handler for salt presence messages
    """

    tag_pattern = re.compile(r'salt/presence/present')

    async def process(self, match: re.Match, data: dict[str, Any]) -> None:
        message = PresenceMessage(
            minions=data['present'],
            master=self.salt_opts['salt_box_master_id'],
            stamp=datetime.fromisoformat(data['_stamp']).timestamp(),
        )

        await self.send_message(message=message, message_tag='presence')

        raise StopProcessing()
