from __future__ import annotations

from enum import Enum

from saltbox_bridge.event_bus.messages.base_messages import BaseMessage


class MasterStatus(str, Enum):
    new = 'new'
    accepted = 'accepted'
    rejected = 'rejected'


class AuthMessage(BaseMessage):
    pubkey: str


class MasterStatusMessage(BaseMessage):
    status: MasterStatus
    is_pubkey_set: bool
