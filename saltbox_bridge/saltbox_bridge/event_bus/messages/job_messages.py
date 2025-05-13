from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from saltbox_bridge.event_bus.messages.base_messages import BaseMessage
from saltbox_bridge.utils.types import SaltTgtType


class NewJobIneMessage(BaseMessage):
    hash_name: str


class NewJobSyncIneMessage(BaseMessage):
    tgt: str
    tgt_type: SaltTgtType
    fun: str
    arg: list
    kwarg: dict
    jid: str | None = None


class JobReturn(BaseModel):
    ret: Any
    retcode: int
    jid: str

    model_config = ConfigDict(extra='allow')


class JobSyncOutMessage(BaseMessage):
    jid: str
    tgt: str
    tgt_type: SaltTgtType
    fun: str
    arg: list
    kwarg: dict
    returns: dict[str, JobReturn]
