from __future__ import annotations

from pydantic import BaseModel

from saltbox_bridge.event_bus.messages.base_messages import BaseMessage


class SlsRepo(BaseModel):
    local_path: str
    name: str
    branch: str


class ListSlsReposMessage(BaseMessage):
    repos: list[SlsRepo]
