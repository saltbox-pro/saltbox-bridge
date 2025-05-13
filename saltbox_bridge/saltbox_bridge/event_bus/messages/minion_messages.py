from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, PositiveInt

from saltbox_bridge.event_bus.messages.base_messages import BaseMessage
from saltbox_bridge.utils.types import SaltTgtType


class GatherMinionsInMessage(BaseMessage):
    tgt: str
    tgt_type: SaltTgtType


class Minion(BaseModel):
    minion_id: str
    master: str


class PresenceMessage(BaseMessage):
    minions: list[str]
    stamp: float


class GrainsOutMessage(BaseMessage):
    grains: dict[str, Any]


class GatherMinionsOutMessage(BaseMessage):
    count: Annotated[int, PositiveInt]
    minions: list[Minion]
