from __future__ import annotations

from saltbox_bridge.event_bus.messages.base_messages import BaseMessage
from saltbox_bridge.utils.types import SaltTgtType


class UpdatePillarCacheInMessage(BaseMessage):
    tgt: str
    tgt_type: SaltTgtType
